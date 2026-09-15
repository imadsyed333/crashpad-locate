# crashpad-locate

Nearest Toronto or Peel intersection for a lat/lon. FastAPI queries PostGIS (KNN); an Airflow DAG loads City of Toronto intersections and derives Peel ones from Street Centre Line.

## Setup

Copy `.env.example` to `.env` and set Airflow credentials. Default `DATABASE_URL` points at the local PostGIS service (`postgis` hostname). For Neon, swap in that connection string (include `sslmode=require`).

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Airflow ETL

```sh
docker compose up
```

Starts PostGIS on port 5432 and Airflow on 8080. Open [http://localhost:8080](http://localhost:8080), then enable and trigger `intersections_etl` (`extract` → `transform` → `load`).

The DAG looks up `Centreline Intersection - 4326.csv` on CKAN (no hardcoded resource UUID), pages Peel Street Centre Line from ArcGIS, writes `data/raw/` and `data/processed/`, then drop-and-inserts `intersections` in PostGIS.

## API

For host-side uvicorn, set `DATABASE_URL` to use `localhost` instead of `postgis`:

```env
DATABASE_URL=postgresql://crashpad:crashpad@localhost:5432/crashpad
```

```sh
uvicorn api.main:app
```

`POST /nearest` body: `{"lat": 43.65, "lon": -79.38}`

```json
{"name": "Yonge St / Dundas St E", "distance_m": 42.3, "direction": "North"}
```

`direction` is `North`/`East`/`South`/`West` from the intersection toward the query point, or `null` when distance is 0. Empty table returns 503.

## Cardinal helper

```sh
python src/geo.py
```
