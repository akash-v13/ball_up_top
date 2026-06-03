"""api/routers/plays.py — Named-play library + probability estimation."""

import sqlite3
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db
from api.schemas import (
    PlaySummary, PlayDetail, RoleAction, PlayFrame,
    PlayProbabilityRequest, PlayProbabilityResponse, PlayBreakdownRow,
)
from ml.play_probability import (
    PlayProbabilityEstimator, load_play_from_db, list_plays as list_plays_db,
)

router = APIRouter()


@router.get("/plays", response_model=list[PlaySummary])
def list_plays(
    team:   Optional[str] = Query(None),
    family: Optional[str] = Query(None),
    season: Optional[str] = Query(None),
    conn:   sqlite3.Connection = Depends(get_db),
):
    rows = list_plays_db(conn, team=team, family=family, season=season)
    return [PlaySummary(**r) for r in rows]


@router.get("/plays/{play_id}", response_model=PlayDetail)
def get_play(play_id: str, conn: sqlite3.Connection = Depends(get_db)):
    play = load_play_from_db(conn, play_id)
    if play is None:
        raise HTTPException(status_code=404, detail=f"Play {play_id!r} not found")

    return PlayDetail(
        play_id=play["play_id"],
        name=play["name"],
        family=play["family"],
        team=play["team"],
        season=play["season"],
        source_page=play["source_page"],
        description=play.get("description"),
        role_actions={
            role: RoleAction(**info) for role, info in play["role_actions"].items()
        },
        shooters=play["shooters"],
        frames=[PlayFrame(**f) for f in play["frames"]],
    )


@router.post("/plays/{play_id}/probability", response_model=PlayProbabilityResponse)
def play_probability(
    play_id: str,
    req: PlayProbabilityRequest,
    conn: sqlite3.Connection = Depends(get_db),
):
    play = load_play_from_db(conn, play_id)
    if play is None:
        raise HTTPException(status_code=404, detail=f"Play {play_id!r} not found")

    estimator = PlayProbabilityEstimator(season=req.season)
    try:
        result = estimator.estimate(
            play=play,
            offense_ids=req.offense_ids,
            defense_ids=req.defense_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PlayProbabilityResponse(
        play_id=result.play_id,
        play_name=result.play_name,
        season=result.season,
        predicted_ppp=result.predicted_ppp,
        shooters_avg_ppp=result.shooters_avg_ppp,
        lineup_avg_ppp=result.lineup_avg_ppp,
        role_breakdown=[
            PlayBreakdownRow(**asdict(row)) for row in result.role_breakdown
        ],
        notes=result.notes,
    )
