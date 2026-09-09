# Nearest-intersection API + Airflow ETL

Greenfield FastAPI service that returns the nearest Toronto intersection for one lat/lon via PostGIS KNN, plus a three-step Airflow DAG that loads the City’s intersection file into Neon PostGIS.

This repo is empty aside from the ponytail rule. Build the smallest thing that satisfies the request: one POST endpoint, one Neon table, one Airflow DAG. Mirror the local Airflow layout from [crashpoint-etl](../crashpoint-etl) (`dags/`, `src/`, `scripts/init_airflow.sh`, `docker-compose.yaml`) but do **not** port geopandas or the collision pipeline.

## Implementation checklist

- [ ] Add requirements, `.env.example`, `.gitignore`, README, and Airflow docker-compose + init script
- [ ] Implement 4-point cardinal-from-bearing helper (`N`/`E`/`S`/`W`) and a runnable self-check
- [ ] Implement extract/transform/load into Neon PostGIS (extension, geography column, GIST index)
- [ ] Implement `POST /nearest` via PostGIS KNN + `ST_Distance` / `ST_Azimuth`

## Source data

The [open.toronto.ca dataset page](https://open.toronto.ca/dataset/intersection-file-city-of-toronto/) renders as Retired, but the CKAN package `intersection-file-city-of-toronto` is live (~46,272 rows, last refreshed 2026-09-05).

ETL will:

1. `GET https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show?id=intersection-file-city-of-toronto`
2. Download the WGS84 CSV resource named `Centreline Intersection - 4326.csv` (do not hardcode a resource UUID)

Keep only what the API needs:

- `INTERSECTION_ID` → `id`
- `INTERSECTION_DESC` → `name`
- lon/lat from `LATITUDE`/`LONGITUDE` if present, otherwise parse `geometry` GeoJSON (`coordinates: [lon, lat]`)

Drop null names/coords and duplicate `INTERSECTION_ID`s (multi-elevation rows share an id). No geopandas.

## Database (Neon + PostGIS)

One table, created by the ETL. No Alembic. On first load:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS intersections (
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  geom geography(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS intersections_geom_gix ON intersections USING gist (geom);
```

Neon has PostGIS available; `CREATE EXTENSION` is enough (no extra Neon UI step unless the project has extensions locked down).

Full refresh in a transaction: load a staging table with `id`, `name`, `lon`, `lat`, then

```sql
TRUNCATE intersections;
INSERT INTO intersections (id, name, geom)
SELECT id, name, ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
FROM stg;
```

`DATABASE_URL` from the environment for both Airflow and the API.

## Airflow ETL

Three `PythonOperator` tasks, daily schedule (source refresh rate is daily):

```
extract >> transform >> load
```

- **extract** — CKAN `package_show` + download 4326 CSV → `data/raw/intersections.csv`
- **transform** — trim/rename/parse coords → `data/processed/intersections.csv`
- **load** — `CREATE EXTENSION postgis` if needed, truncate-and-insert `geography(Point, 4326)` into Neon

Logic lives in [`src/etl.py`](src/etl.py); the DAG in [`dags/intersections_etl.py`](dags/intersections_etl.py) only wires tasks. Docker Compose matches the sibling Airflow 2.8.1 image, with `_PIP_ADDITIONAL_REQUIREMENTS=pandas psycopg[binary]`.

## FastAPI

Single endpoint, no extra routers/services packages:

`POST /nearest` body: `{"lat": 43.65, "lon": -79.38}`

Validate ranges (`lat` ∈ [-90, 90], `lon` ∈ [-180, 180]). One PostGIS query: KNN to the nearest point, metres via `geography`, bearing from the **intersection → query point**.

```sql
SELECT
  name,
  ST_Distance(geom, q) AS distance_m,
  degrees(ST_Azimuth(geom::geometry, q::geometry)) AS bearing_deg
FROM intersections,
     ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography AS q
ORDER BY geom <-> q
LIMIT 1;
```

`ST_Distance` on `geography` returns metres. `ST_Azimuth` is clockwise from north. Map `bearing_deg` to one of the four major cardinals in Python (90° sectors, midpoints inclusive toward the clockwise cardinal: N 315–45, E 45–135, S 135–225, W 225–315).

Response:

```json
{"name": "Yonge St / Dundas St E", "distance_m": 42.3, "direction": "N"}
```

- Distance in **metres** (`distance_m`; `ST_Distance` on `geography` already returns metres — do not convert)
- Direction is **4-point** compass only (`N`, `E`, `S`, `W`). If distance is ~0, `direction` is `null`
- 503 if the table is empty

Pydantic models and the SQL live in [`api/main.py`](api/main.py). Cardinal-from-bearing helper in [`src/geo.py`](src/geo.py) so it can be unit-tested without standing up the app.

## Layout

```
api/main.py
src/etl.py
src/geo.py
dags/intersections_etl.py
scripts/init_airflow.sh
tests/test_geo.py
docker-compose.yaml
requirements.txt          # fastapi, uvicorn, psycopg[binary], pandas
.env.example              # DATABASE_URL, AIRFLOW_USERNAME, AIRFLOW_PASSWORD, AIRFLOW_UID
.gitignore
README.md
```

No API container — run with `uvicorn api.main:app`. Airflow is the only Compose service, same as crashpoint-etl.

## Check

[`tests/test_geo.py`](tests/test_geo.py) or an `if __name__ == "__main__"` self-check in [`src/geo.py`](src/geo.py): known bearings (0° → `N`, 90° → `E`, 180° → `S`, 270° → `W`). Distance and KNN stay in PostGIS — no Python haversine. Prefer the self-check over adding pytest.
