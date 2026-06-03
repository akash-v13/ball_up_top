"""api/routers/prediction.py — LineupModel-backed numeric predictions."""

import logging

from fastapi import APIRouter, HTTPException

from api.deps import get_lineup_model
from api.schemas import (
    LineupPredictRequest, LineupPredictResponse,
    MatchupPredictRequest, MatchupPredictResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_model():
    model = get_lineup_model()
    if model is None:
        raise HTTPException(
            status_code=503,
            detail="LineupModel not loaded. Train via "
                   "LineupModel(season=...).train(); model.save() first.",
        )
    return model


@router.post("/lineup/predict", response_model=LineupPredictResponse)
def predict_lineup(req: LineupPredictRequest):
    model = _require_model()
    try:
        rating = model.predict_lineup(req.player_ids)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LineupPredictResponse(
        predicted_net_rating=round(rating, 3),
        season=req.season,
        player_ids=req.player_ids,
    )


@router.post("/matchup/predict", response_model=MatchupPredictResponse)
def predict_matchup(req: MatchupPredictRequest):
    model = _require_model()
    try:
        off = model.predict_lineup(req.offense_ids)
        defn = model.predict_lineup(req.defense_ids)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MatchupPredictResponse(
        predicted_diff=round(off - defn, 3),
        offense_net_rating=round(off, 3),
        defense_net_rating=round(defn, 3),
        season=req.season,
    )
