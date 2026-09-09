import json
import os
import shutil
import urllib.request
from pathlib import Path

import pandas as pd
import psycopg

CKAN_PACKAGE = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show"
    "?id=intersection-file-city-of-toronto"
)
RESOURCE_NAME = "Centreline Intersection - 4326.csv"
DATA = Path("/opt/airflow/data")


def extract():
    raw = DATA / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(CKAN_PACKAGE, timeout=60) as resp:
        pkg = json.load(resp)
    url = next(r["url"] for r in pkg["result"]["resources"] if r["name"] == RESOURCE_NAME)
    dest = raw / "intersections.csv"
    with urllib.request.urlopen(url, timeout=120) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def _parse_geom(value):
    if pd.isna(value) or not str(value).strip():
        return None
    geom = json.loads(value) if isinstance(value, str) else value
    coords = geom.get("coordinates") or []
    if not coords:
        return None
    # Point [lon, lat] or MultiPoint [[lon, lat], ...]
    pt = coords[0] if isinstance(coords[0], (list, tuple)) else coords
    return float(pt[0]), float(pt[1])


def transform():
    df = pd.read_csv(DATA / "raw" / "intersections.csv")
    out = pd.DataFrame({
        "id": df["INTERSECTION_ID"],
        "name": df["INTERSECTION_DESC"].str.strip(),
    })
    if {"LATITUDE", "LONGITUDE"}.issubset(df.columns):
        out["lat"] = pd.to_numeric(df["LATITUDE"], errors="coerce")
        out["lon"] = pd.to_numeric(df["LONGITUDE"], errors="coerce")
    else:
        parsed = df["geometry"].map(_parse_geom)
        out["lon"] = parsed.map(lambda p: None if p is None else p[0])
        out["lat"] = parsed.map(lambda p: None if p is None else p[1])
    out = out.dropna(subset=["id", "name", "lon", "lat"])
    out = out[out["name"] != ""]
    out["id"] = out["id"].astype(int)
    out = out.drop_duplicates("id")
    processed = DATA / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    out[["id", "name", "lon", "lat"]].to_csv(processed / "intersections.csv", index=False)


def load():
    df = pd.read_csv(DATA / "processed" / "intersections.csv")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS intersections (
              id   INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              geom geography(Point, 4326) NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS intersections_geom_gix ON intersections USING gist (geom)"
        )
        conn.execute("DROP TABLE IF EXISTS stg")
        conn.execute(
            "CREATE TEMP TABLE stg (id INTEGER, name TEXT, lon DOUBLE PRECISION, lat DOUBLE PRECISION)"
        )
        with conn.cursor() as cur:
            with cur.copy("COPY stg (id, name, lon, lat) FROM STDIN") as copy:
                for id_, name, lon, lat in df.itertuples(index=False, name=None):
                    copy.write_row((int(id_), name, float(lon), float(lat)))
        conn.execute("TRUNCATE intersections")
        conn.execute("""
            INSERT INTO intersections (id, name, geom)
            SELECT id, name, ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
            FROM stg
        """)
