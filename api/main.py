"""api/main.py — FastAPI application entry point.

Run locally:
    uvicorn api.main:app --reload
    # or, for the one-click desktop-style launch:
    python start.py

Endpoints overview:
    GET  /                     (the whiteboard frontend)
    GET  /health
    GET  /teams
    GET  /teams/{team_id}/roster?season=
    GET  /players?search=&limit=
    GET  /players/{player_id}
    GET  /players/{player_id}/synergy?season=
    GET  /players/{player_id}/matchups?role=defender|offender&top_n=
    GET  /games/{game_id}/possessions?period=
    GET  /games/{game_id}/shots?player_id=
    POST /lineup/predict
    POST /matchup/predict
    POST /plays/recommend
"""

import logging
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.deps import load_lineup_model_if_present
from api.routers import reference, data, prediction, recommend, plays

FRONTEND_DIR = pathlib.Path(__file__).parent.parent / "frontend"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting NBA analytics API …")
    load_lineup_model_if_present()
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="NBA Analytics Platform",
    description="Lineup efficiency, play recommendations, and per-game data.",
    version="0.1.0",
    lifespan=lifespan,
)

# Open CORS so the static whiteboard.html (file://) and any local React dev
# server can call the API without preflight friction. Tighten before any
# real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root():
    """Serve the whiteboard as the app's landing page.

    no-store headers on this route so the browser always pulls the latest
    HTML when the dev iterates on the frontend. Otherwise reloads silently
    show stale markup and the JS never runs against the updated DOM.
    """
    return FileResponse(
        FRONTEND_DIR / "whiteboard.html",
        headers={"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"},
    )


# Any other static file in frontend/ (assets, future pages) is served under /app/.
if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR), name="frontend")


app.include_router(reference.router,  tags=["reference"])
app.include_router(data.router,       tags=["data"])
app.include_router(prediction.router, tags=["prediction"])
app.include_router(recommend.router,  tags=["recommend"])
app.include_router(plays.router,      tags=["plays"])
