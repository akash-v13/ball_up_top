"""api/routers/reference.py — Teams, players, rosters, synergy lookups."""

import logging
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db
from api.schemas import Team, Player, RosterEntry, SynergyRow

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/teams", response_model=list[Team])
def list_teams(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT team_id, abbreviation, full_name, conference, division "
        "FROM teams ORDER BY full_name"
    ).fetchall()
    return [Team(**dict(r)) for r in rows]


@router.get("/teams/{team_id}/roster", response_model=list[RosterEntry])
def team_roster(
    team_id: int,
    season: str = Query(..., description="e.g. 2024-25"),
    conn: sqlite3.Connection = Depends(get_db),
):
    rows = conn.execute(
        """
        SELECT p.player_id,
               p.first_name || ' ' || p.last_name AS full_name,
               p.position,
               r.jersey_number
        FROM rosters r
        JOIN players p ON p.player_id = r.player_id
        WHERE r.team_id = ? AND r.season = ?
        ORDER BY p.last_name
        """,
        (team_id, season),
    ).fetchall()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No roster found for team {team_id} season {season}. "
                   "Run ingest_reference.py first.",
        )
    return [RosterEntry(**dict(r)) for r in rows]


@router.get("/players", response_model=list[Player])
def search_players(
    search: Optional[str] = Query(None, description="Partial name match"),
    limit: int = Query(25, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_db),
):
    if search:
        like = f"%{search}%"
        rows = conn.execute(
            """
            SELECT player_id, first_name, last_name,
                   first_name || ' ' || last_name AS full_name,
                   position, is_active
            FROM players
            WHERE first_name LIKE ? OR last_name LIKE ?
               OR (first_name || ' ' || last_name) LIKE ?
            ORDER BY is_active DESC, last_name
            LIMIT ?
            """,
            (like, like, like, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT player_id, first_name, last_name, "
            "first_name || ' ' || last_name AS full_name, position, is_active "
            "FROM players ORDER BY last_name LIMIT ?",
            (limit,),
        ).fetchall()
    return [Player(**dict(r)) for r in rows]


@router.get("/players/{player_id}", response_model=Player)
def get_player(player_id: int, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute(
        "SELECT player_id, first_name, last_name, "
        "first_name || ' ' || last_name AS full_name, position, is_active "
        "FROM players WHERE player_id = ?",
        (player_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found")
    return Player(**dict(row))


@router.get("/players/{player_id}/synergy", response_model=list[SynergyRow])
def player_synergy(
    player_id: int,
    season: str = Query(..., description="e.g. 2024-25"),
    conn: sqlite3.Connection = Depends(get_db),
):
    rows = conn.execute(
        """
        SELECT play_type, ppp, efg_pct, fg_pct, tov_pct, percentile
        FROM synergy_play_types
        WHERE player_id = ? AND season = ? AND type_grouping = 'offensive'
        ORDER BY ppp DESC
        """,
        (player_id, season),
    ).fetchall()
    return [SynergyRow(**dict(r)) for r in rows]
