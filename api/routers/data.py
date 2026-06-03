"""api/routers/data.py — Game-level + player-level analytical data endpoints."""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db
from api.schemas import (
    Possession, Shot, MatchupRow,
    PossessionSearchRequest, PossessionSearchResponse,
)

router = APIRouter()


@router.get("/games/{game_id}/possessions", response_model=list[Possession])
def game_possessions(
    game_id: str,
    period: Optional[int] = Query(None, ge=1, le=10),
    conn: sqlite3.Connection = Depends(get_db),
):
    sql = (
        "SELECT possession_id, period, start_clock_s, end_clock_s, "
        "       offense_team_id, defense_team_id, "
        "       play_type, play_type_source, outcome, points, "
        "       start_type, video_url "
        "FROM possession_events WHERE game_id = ?"
    )
    params: list = [game_id]
    if period is not None:
        sql += " AND period = ?"
        params.append(period)
    sql += " ORDER BY period ASC, start_clock_s DESC"
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No possessions for game {game_id}. "
                   "Run ingest_bulk for pbpstats or derive_possessions.py.",
        )
    return [Possession(**dict(r)) for r in rows]


@router.get("/games/{game_id}/shots", response_model=list[Shot])
def game_shots(
    game_id: str,
    player_id: Optional[int] = Query(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    sql = (
        "SELECT event_id, player_id, team_id, period, "
        "       action_type, shot_type, shot_zone_basic, shot_zone_area, "
        "       shot_distance, loc_x, loc_y, made_flag "
        "FROM shot_charts WHERE game_id = ?"
    )
    params: list = [game_id]
    if player_id is not None:
        sql += " AND player_id = ?"
        params.append(player_id)
    sql += " ORDER BY period, event_id"
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No shots for game {game_id} (player_id={player_id}).",
        )
    return [
        Shot(
            event_id=r["event_id"], player_id=r["player_id"], team_id=r["team_id"],
            period=r["period"], action_type=r["action_type"], shot_type=r["shot_type"],
            shot_zone_basic=r["shot_zone_basic"], shot_zone_area=r["shot_zone_area"],
            shot_distance=r["shot_distance"], loc_x=r["loc_x"], loc_y=r["loc_y"],
            made=bool(r["made_flag"]),
        )
        for r in rows
    ]


@router.post("/possessions/search", response_model=PossessionSearchResponse)
def search_possessions(
    req: PossessionSearchRequest,
    conn: sqlite3.Connection = Depends(get_db),
):
    """
    Slice the possession_events table by any combination of filters.
    All filters are optional; pagination via limit (max 500) + offset.
    """
    where: list[str] = []
    params: list = []

    # Season filter requires a games join.
    needs_join = req.season is not None
    if needs_join:
        where.append("g.season = ?")
        params.append(req.season)

    if req.start_type is not None:
        where.append("pe.start_type = ?"); params.append(req.start_type)
    if req.outcome is not None:
        where.append("pe.outcome = ?"); params.append(req.outcome)
    if req.play_type is not None:
        where.append("pe.play_type = ?"); params.append(req.play_type)
    if req.play_type_source is not None:
        where.append("pe.play_type_source = ?"); params.append(req.play_type_source)
    if req.offense_team_id is not None:
        where.append("pe.offense_team_id = ?"); params.append(req.offense_team_id)
    if req.defense_team_id is not None:
        where.append("pe.defense_team_id = ?"); params.append(req.defense_team_id)
    if req.min_points is not None:
        where.append("pe.points >= ?"); params.append(req.min_points)
    if req.max_points is not None:
        where.append("pe.points <= ?"); params.append(req.max_points)
    if req.has_video is True:
        where.append("pe.video_url IS NOT NULL")
    elif req.has_video is False:
        where.append("pe.video_url IS NULL")

    join_sql = " JOIN games g ON g.game_id = pe.game_id" if needs_join else ""
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM possession_events pe{join_sql}{where_sql}",
        params,
    ).fetchone()[0]

    rows = conn.execute(
        f"""
        SELECT pe.possession_id, pe.game_id, pe.period,
               pe.start_clock_s, pe.end_clock_s,
               pe.offense_team_id, pe.defense_team_id,
               pe.play_type, pe.play_type_source, pe.outcome, pe.points,
               pe.start_type, pe.video_url
        FROM possession_events pe{join_sql}{where_sql}
        ORDER BY pe.possession_id
        LIMIT ? OFFSET ?
        """,
        [*params, req.limit, req.offset],
    ).fetchall()

    return PossessionSearchResponse(
        total=total, limit=req.limit, offset=req.offset,
        results=[Possession(**dict(r)) for r in rows],
    )


@router.get("/players/{player_id}/matchups", response_model=list[MatchupRow])
def player_matchups(
    player_id: int,
    role: str = Query("defender", pattern="^(defender|offender)$"),
    top_n: int = Query(20, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_db),
):
    column = "defender_id" if role == "defender" else "offender_id"
    rows = conn.execute(
        f"""
        SELECT game_id, defender_id, offender_id,
               matchup_minutes, partial_possessions, player_points,
               matchup_fgm, matchup_fga, matchup_fg3m, matchup_fg3a
        FROM player_matchups
        WHERE {column} = ?
        ORDER BY partial_possessions DESC
        LIMIT ?
        """,
        (player_id, top_n),
    ).fetchall()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No matchup data for player {player_id} as {role}",
        )
    return [MatchupRow(**dict(r)) for r in rows]
