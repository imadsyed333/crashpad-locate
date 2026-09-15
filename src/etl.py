import json
import os
import shutil
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import psycopg

CKAN_PACKAGE = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show"
    "?id=intersection-file-city-of-toronto"
)
RESOURCE_NAME = "Centreline Intersection - 4326.csv"
PEEL_LAYER = (
    "https://services6.arcgis.com/ONZht79c8QWuX759/arcgis/rest/services"
    "/Street_Centre_Line/FeatureServer/0/query"
)
PEEL_PAGE = 2000
PEEL_FIELDS = "FNODE_,TNODE_,FULLSTNAME,PRIVATE"
DATA = Path(os.environ.get("DATA_DIR", "/opt/airflow/data"))


def _get_json(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "crashpad-locate"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def extract():
    raw = DATA / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    _extract_toronto(raw)
    _extract_peel(raw)


def _extract_toronto(raw):
    pkg = _get_json(CKAN_PACKAGE, timeout=60)
    url = next(r["url"] for r in pkg["result"]["resources"] if r["name"] == RESOURCE_NAME)
    dest = raw / "intersections.csv"
    req = urllib.request.Request(url, headers={"User-Agent": "crashpad-locate"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def _extract_peel(raw):
    features = []
    offset = 0
    while True:
        params = urlencode({
            "where": "1=1",
            "outFields": PEEL_FIELDS,
            "f": "geojson",
            "outSR": 4326,
            "resultRecordCount": PEEL_PAGE,
            "resultOffset": offset,
        })
        page = _get_json(f"{PEEL_LAYER}?{params}")
        batch = page.get("features") or []
        if not batch:
            break
        features.extend(batch)
        if len(batch) < PEEL_PAGE:
            break
        offset += len(batch)
    with open(raw / "peel_streets.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)


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


def _path_coords(geom):
    coords = (geom or {}).get("coordinates") or []
    if (geom or {}).get("type") == "MultiLineString":
        return coords[0] if coords else []
    return coords


def intersections_from_segments(features):
    """Group centreline endpoints by FNODE_/TNODE_ into named intersections.

    ponytail: misses un-noded mid-block crossings; a grade-separated pair that
    incorrectly shares a node looks like an intersection. Geometric snap is the upgrade.
    """
    nodes = {}
    for feat in features:
        props = feat.get("properties") or {}
        if str(props.get("PRIVATE") or "").upper() == "Y":
            continue
        name = (props.get("FULLSTNAME") or "").strip()
        if not name:
            continue
        path = _path_coords(feat.get("geometry"))
        if len(path) < 2:
            continue
        for node_id, pt in ((props.get("FNODE_"), path[0]), (props.get("TNODE_"), path[-1])):
            if node_id is None or (isinstance(node_id, float) and pd.isna(node_id)):
                continue
            node_id = int(node_id)
            rec = nodes.get(node_id)
            if rec is None:
                nodes[node_id] = {"names": {name}, "lon": float(pt[0]), "lat": float(pt[1])}
            else:
                rec["names"].add(name)
    return [
        {
            "id": f"peel:{node_id}",
            "name": " / ".join(sorted(rec["names"])),
            "lon": rec["lon"],
            "lat": rec["lat"],
        }
        for node_id, rec in nodes.items()
        if len(rec["names"]) >= 2
    ]


def _check_intersections_from_segments():
    features = [
        {
            "properties": {"FNODE_": 1, "TNODE_": 10, "FULLSTNAME": "MAIN ST", "PRIVATE": None},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]},
        },
        {
            "properties": {"FNODE_": 1, "TNODE_": 20, "FULLSTNAME": "SIDE ST", "PRIVATE": None},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [0, 1]]},
        },
        {
            "properties": {"FNODE_": 2, "TNODE_": 3, "FULLSTNAME": "CUL DE SAC", "PRIVATE": None},
            "geometry": {"type": "LineString", "coordinates": [[5, 5], [6, 6]]},
        },
    ]
    rows = intersections_from_segments(features)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["id"] == "peel:1"
    assert row["name"] == "MAIN ST / SIDE ST"
    assert row["lon"] == 0 and row["lat"] == 0


def transform():
    _transform_toronto()
    _transform_peel()


def _transform_toronto():
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
    out["id"] = "toronto:" + out["id"].astype(int).astype(str)
    out = out.drop_duplicates("id")
    processed = DATA / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    out[["id", "name", "lon", "lat"]].to_csv(processed / "intersections.csv", index=False)


def _transform_peel():
    _check_intersections_from_segments()
    with open(DATA / "raw" / "peel_streets.geojson") as f:
        fc = json.load(f)
    rows = intersections_from_segments(fc.get("features") or [])
    processed = DATA / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["id", "name", "lon", "lat"]).to_csv(
        processed / "peel_intersections.csv", index=False
    )


def load():
    df = pd.concat(
        [
            pd.read_csv(DATA / "processed" / "intersections.csv"),
            pd.read_csv(DATA / "processed" / "peel_intersections.csv"),
        ],
        ignore_index=True,
    )
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        conn.execute("DROP TABLE IF EXISTS intersections")
        conn.execute("""
            CREATE TABLE intersections (
              id   TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              geom geography(Point, 4326) NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX intersections_geom_gix ON intersections USING gist (geom)"
        )
        conn.execute("DROP TABLE IF EXISTS stg")
        conn.execute(
            "CREATE TEMP TABLE stg (id TEXT, name TEXT, lon DOUBLE PRECISION, lat DOUBLE PRECISION)"
        )
        with conn.cursor() as cur:
            with cur.copy("COPY stg (id, name, lon, lat) FROM STDIN") as copy:
                for id_, name, lon, lat in df.itertuples(index=False, name=None):
                    copy.write_row((str(id_), name, float(lon), float(lat)))
        conn.execute("""
            INSERT INTO intersections (id, name, geom)
            SELECT id, name, ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
            FROM stg
        """)


if __name__ == "__main__":
    extract()
    transform()
    load()
