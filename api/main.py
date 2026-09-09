import os

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.geo import cardinal_from_bearing

load_dotenv()

NEAREST_SQL = """
SELECT
  name,
  ST_Distance(geom, q.geog) AS distance_m,
  degrees(ST_Azimuth(geom::geometry, q.geog::geometry)) AS bearing_deg
FROM intersections,
     (SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography) AS q(geog)
ORDER BY geom <-> q.geog
LIMIT 1
"""

app = FastAPI()


class NearestRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class NearestResponse(BaseModel):
    name: str
    distance_m: float
    direction: str | None


@app.post("/nearest", response_model=NearestResponse)
def nearest(body: NearestRequest):
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute(NEAREST_SQL, {"lon": body.lon, "lat": body.lat}).fetchone()
    if row is None:
        raise HTTPException(status_code=503, detail="intersections table is empty")
    name, distance_m, bearing_deg = row
    direction = None if distance_m == 0 or bearing_deg is None else cardinal_from_bearing(bearing_deg)
    return NearestResponse(name=name, distance_m=distance_m, direction=direction)
