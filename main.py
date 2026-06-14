"""
Pavé — Road Cycling Route Planner
Backend: FastAPI + Brouter (fastbike) + ORS fallback
"""
import os
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import httpx, uvicorn

ORS_API_KEY = os.getenv("ORS_API_KEY")

app = FastAPI(title="Pavé API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Coord(BaseModel):
    lat: float
    lng: float

class RouteRequest(BaseModel):
    start: Coord
    end: Coord
    waypoints: list[Coord] = []
    loop: bool = False


def build_lonlats(req: RouteRequest) -> str:
    pts = [req.start] + req.waypoints + [req.end]
    if req.loop:
        pts.append(req.start)
    return '|'.join(f"{p.lng},{p.lat}" for p in pts)


@app.get("/geocode")
async def geocode(q: str):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 5, "addressdetails": 1},
            headers={
                "User-Agent": "Pave-CyclingApp/1.0 (https://pave.onrender.com)",
                "Accept-Language": "es,en",
            }
        )
        r.raise_for_status()
    return [{"name": i["display_name"], "lat": float(i["lat"]), "lng": float(i["lon"])} for i in r.json()]


@app.post("/route")
async def route(req: RouteRequest):
    lonlats = build_lonlats(req)

    # ── Brouter (motor principal) ─────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                "https://brouter.de/brouter",
                params={
                    "lonlats":        lonlats,
                    "profile":        "fastbike",
                    "alternativeidx": "0",
                    "format":         "geojson"
                }
            )
        if r.status_code == 200:
            return _parse_brouter(r.json())
    except Exception:
        pass  # fallback a ORS

    # ── ORS fallback ──────────────────────────────────────────────────
    if not ORS_API_KEY:
        raise HTTPException(503, "Brouter no disponible y ORS_API_KEY no configurada")

    coords = [[req.start.lng, req.start.lat]]
    for wp in req.waypoints:
        coords.append([wp.lng, wp.lat])
    coords.append([req.end.lng, req.end.lat])
    if req.loop:
        coords.append([req.start.lng, req.start.lat])

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            "https://api.heigit.org/openrouteservice/v2/directions/cycling-road/geojson",
            headers={"Authorization": ORS_API_KEY, "Content-Type": "application/json"},
            json={"coordinates": coords, "instructions": True, "elevation": True}
        )
        if r.status_code == 403:
            raise HTTPException(403, "ORS API key inválida")
        r.raise_for_status()

    feat  = r.json()["features"][0]
    props = feat["properties"]
    summ  = props["summary"]
    geo   = feat["geometry"]["coordinates"]

    sub, baj = 0.0, 0.0
    for i in range(1, len(geo)):
        if len(geo[i]) > 2 and len(geo[i-1]) > 2:
            d = geo[i][2] - geo[i-1][2]
            if d > 0: sub += d
            else:     baj += abs(d)

    steps = []
    for seg in props.get("segments", []):
        for s in seg.get("steps", []):
            steps.append({
                "texto":       s.get("instruction", ""),
                "distancia_m": round(s.get("distance", 0)),
                "type":        s.get("type", 0),
            })

    return {
        "distancia_km": round(summ["distance"] / 1000, 2),
        "duracion_min": round(summ["duration"] / 60),
        "subida_m":     round(sub),
        "bajada_m":     round(baj),
        "geometry":     geo,
        "steps":        steps,
        "motor":        "ors"
    }


def _parse_brouter(data: dict) -> dict:
    feat  = data["features"][0]
    props = feat["properties"]
    geo   = feat["geometry"]["coordinates"]  # [lng, lat, ele]

    km  = round(int(props.get("track-length", 0)) / 1000, 2)
    min_= round(int(props.get("total-time",   0)) / 60)
    asc = round(float(props.get("filtered ascend", 0)))
    dsc = round(float(props.get("filtered descend", 0)))

    # Mensajes de giro desde los waypoints de Brouter
    steps = []
    for msg in props.get("messages", []):
        if len(msg) >= 4:
            steps.append({
                "texto":       msg[3] if len(msg) > 3 else "",
                "distancia_m": int(msg[1]) if msg[1].isdigit() else 0,
                "type":        0,
            })

    return {
        "distancia_km": km,
        "duracion_min": min_,
        "subida_m":     asc,
        "bajada_m":     dsc,
        "geometry":     geo,
        "steps":        steps,
        "motor":        "brouter"
    }


@app.post("/export/gpx")
async def export_gpx(req: RouteRequest):
    lonlats = build_lonlats(req)

    # Brouter devuelve GPX directamente
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                "https://brouter.de/brouter",
                params={
                    "lonlats":        lonlats,
                    "profile":        "fastbike",
                    "alternativeidx": "0",
                    "format":         "gpx"
                }
            )
        if r.status_code == 200:
            return Response(
                content=r.content,
                media_type="application/gpx+xml",
                headers={"Content-Disposition": 'attachment; filename="pave.gpx"'}
            )
    except Exception:
        pass

    # Fallback: construir GPX desde la ruta calculada
    rt = await route(req)
    now = datetime.utcnow().isoformat() + "Z"
    pts = "".join(
        f'<trkpt lat="{p[1]:.6f}" lon="{p[0]:.6f}"><ele>{p[2] if len(p)>2 else 0:.1f}</ele></trkpt>'
        for p in rt["geometry"]
    )
    gpx = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="Pavé">'
        f'<metadata><name>Pavé</name><time>{now}</time>'
        f'<desc>{rt["distancia_km"]} km — subida {rt["subida_m"]} m</desc></metadata>'
        f'<trk><name>Pavé</name><type>cycling</type><trkseg>{pts}</trkseg></trk>'
        '</gpx>'
    )
    return Response(
        content=gpx,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": 'attachment; filename="pave.gpx"'}
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"🚴 Pavé corriendo en http://localhost:{port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)