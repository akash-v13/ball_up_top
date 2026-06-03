"""api/deps.py — Shared dependencies (DB session, model accessors)."""

import logging
import pathlib
import sys
from typing import Iterator, Optional

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from db.database import get_connection, DB_PATH
from ml.features import FeatureStore
from ml.lineup_model import LineupModel, MODEL_FILE
from ml.play_recommender import PlayRecommender

logger = logging.getLogger(__name__)


def get_db() -> Iterator:
    """FastAPI dependency: open a connection per request, close on completion."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Cached per-season instances
# ---------------------------------------------------------------------------
# FeatureStore caches DataFrames internally; instantiate once per season and
# reuse across requests. Models are loaded eagerly at startup if a file exists.

_feature_stores: dict[str, FeatureStore] = {}
_lineup_model:   Optional[LineupModel]   = None
_recommenders:   dict[str, PlayRecommender] = {}


def get_feature_store(season: str) -> FeatureStore:
    if season not in _feature_stores:
        _feature_stores[season] = FeatureStore(season=season)
    return _feature_stores[season]


def get_recommender(season: str) -> PlayRecommender:
    if season not in _recommenders:
        _recommenders[season] = PlayRecommender(season=season)
    return _recommenders[season]


def get_lineup_model() -> Optional[LineupModel]:
    """Returns the loaded model or None if no saved file exists."""
    return _lineup_model


def load_lineup_model_if_present() -> None:
    """Called at app startup. Sets the cached model or leaves it None."""
    global _lineup_model
    if MODEL_FILE.exists():
        try:
            _lineup_model = LineupModel.load()
            logger.info("LineupModel loaded — season=%s", _lineup_model.season)
        except Exception as exc:
            logger.warning("Failed to load LineupModel: %s", exc)
            _lineup_model = None
    else:
        logger.info("No saved LineupModel at %s — predict endpoints will 503", MODEL_FILE)
        _lineup_model = None
