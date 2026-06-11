# 🚴 Pavé — Rutas Bici de Carretera

Planificador de rutas para ciclismo de carretera con exportación GPX.

## Estructura

```
pave/
├── main.py           ← Backend FastAPI
├── requirements.txt
├── Procfile          ← Para Render/Railway
├── .env.example
└── frontend/
    └── index.html    ← App completa
```

## Desplegar en Render (gratis)

1. **Sube este repo a GitHub**
   ```bash
   git init
   git add .
   git commit -m "first commit"
   git remote add origin https://github.com/TUUSUARIO/pave.git
   git push -u origin main
   ```

2. **Crea un Web Service en Render**
   - Ve a [render.com](https://render.com) → New → Web Service
   - Conecta tu repo de GitHub
   - Render detecta el `Procfile` automáticamente
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

3. **Añade la variable de entorno**
   - En Render → Environment → Add variable:
     - Key: `ORS_API_KEY`
     - Value: tu key de [openrouteservice.org](https://openrouteservice.org/dev/#/signup)

4. **Deploy** → Render te da una URL tipo `https://pave.onrender.com`

> ⚠️ El plan gratuito de Render duerme tras 15 min sin tráfico.
> El primer request puede tardar ~30s en despertar (el frontend ya avisa).

## Desarrollo local

```bash
pip install -r requirements.txt
ORS_API_KEY=tu_key python main.py
# → http://localhost:8000
```

Para desarrollo local, cambia en `frontend/index.html`:
```js
const API = 'http://localhost:8000';
```
