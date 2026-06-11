"""
Pavé — Road Cycling Route Planner
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
if not ORS_API_KEY:
    raise RuntimeError("Falta la variable de entorno ORS_API_KEY")

app = FastAPI(title="Pavé API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Coord(BaseModel):
    lat: float
    lng: float

class RouteRequest(BaseModel):
    start: Coord
    end: Coord
    waypoints: list[Coord] = []
    avoid_features: list[str] = []


@app.get("/geocode")
async def geocode(q: str):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 5, "addressdetails": 1},
            headers={
                "User-Agent": "Pave-CyclingApp/1.0 (https://pave.onrender.com)",
                "Accept-Language": "es,en",
                "Referer": "https://pave.onrender.com"
            }
        )
        r.raise_for_status()
    return [{"name": i["display_name"], "lat": float(i["lat"]), "lng": float(i["lon"])} for i in r.json()]


@app.post("/route")
async def route(req: RouteRequest):
    coords = [[req.start.lng, req.start.lat]]
    for wp in req.waypoints:
        coords.append([wp.lng, wp.lat])
    coords.append([req.end.lng, req.end.lat])

    # Autopistas siempre evitadas + opciones del usuario
    avoid = list(set(req.avoid_features + ["highways"]))
    opts = {"avoid_features": avoid}

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            "https://api.heigit.org/openrouteservice/v2/directions/cycling-road/geojson",
            headers={"Authorization": ORS_API_KEY, "Content-Type": "application/json"},
            json={"coordinates": coords, "instructions": True, "elevation": True, "options": opts}
        )
        if r.status_code == 403:
            raise HTTPException(403, "ORS API key inválida")
        if r.status_code == 400:
            # Intentar extraer el mensaje de ORS
            try:
                msg = r.json().get("error", {}).get("message", "Coordenadas inválidas o ruta no encontrada")
            except Exception:
                msg = "No se encontró ruta entre esos puntos"
            raise HTTPException(400, msg)
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
    }


@app.post("/export/gpx")
async def export_gpx(req: RouteRequest):
    r = await route(req)
    now = datetime.utcnow().isoformat() + "Z"
    pts = "".join(
        f'<trkpt lat="{p[1]:.6f}" lon="{p[0]:.6f}"><ele>{p[2] if len(p)>2 else 0:.1f}</ele></trkpt>'
        for p in r["geometry"]
    )
    gpx = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="Pavé">'
        f'<metadata><name>Pavé</name><time>{now}</time>'
        f'<desc>{r["distancia_km"]} km — subida {r["subida_m"]} m</desc></metadata>'
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