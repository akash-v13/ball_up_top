"""api/routers/recommend.py — Synergy / model-mode play recommendations."""

import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from api.deps import get_recommender
from api.schemas import (
    RecommendRequest, RecommendResponse, PlayRecommendation,
    PlayerRoleOut, WhiteboardInstructions, WhiteboardPlayer,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _to_response(rec) -> PlayRecommendation:
    """Convert the dataclass-based PlayRecommendation to the Pydantic model."""
    d = asdict(rec)
    wb = d["whiteboard_instructions"] or {}
    wb_obj = WhiteboardInstructions(
        play_type=wb.get("play_type", rec.play_type),
        diagram_key=wb.get("diagram_key", rec.diagram_key),
        players=[WhiteboardPlayer(**p) for p in wb.get("players", [])],
        ball_start=wb.get("ball_start", {"x": 0.0, "y": 0.0}),
    )
    return PlayRecommendation(
        rank=rec.rank,
        play_type=rec.play_type,
        display_name=rec.display_name,
        predicted_ppp=rec.predicted_ppp,
        confidence=rec.confidence,
        method=rec.method,
        diagram_key=rec.diagram_key,
        explanation=rec.explanation,
        player_roles=[PlayerRoleOut(**asdict(r)) for r in rec.player_roles],
        whiteboard_instructions=wb_obj,
    )


@router.post("/plays/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest):
    recommender = get_recommender(req.season)
    try:
        recs = recommender.recommend(
            offense_ids=req.offense_ids,
            defense_ids=req.defense_ids,
            top_n=req.top_n,
            method=req.method,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RecommendResponse(
        season=req.season,
        method=req.method,
        recommendations=[_to_response(r) for r in recs],
    )
