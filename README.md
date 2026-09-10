# crashpad-locate

Nearest Toronto intersection for a lat/lon. FastAPI queries Neon PostGIS (KNN); an Airflow DAG loads the City intersection file daily.

## Setup

Copy `.env.example` to `.env` and set `DATABASE_URL` (Neon Postgres with PostGIS) plus Airflow credentials.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Airflow ETL

```sh
docker compose up
```

Open [http://localhost:8080](http://localhost:8080), then enable and trigger `intersections_etl` (`extract` → `transform` → `load`).

The DAG looks up `Centreline Intersection - 4326.csv` on CKAN (no hardcoded resource UUID), writes `data/raw/` and `data/processed/`, then truncate-and-inserts `intersections` in Neon.

## API

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
