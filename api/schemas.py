"""api/schemas.py — Pydantic request/response models for every endpoint."""

from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Reference
# ---------------------------------------------------------------------------

class Team(BaseModel):
    team_id:      int
    abbreviation: str
    full_name:    str
    conference:   Optional[str] = None
    division:     Optional[str] = None


class Player(BaseModel):
    player_id:  int
    first_name: str
    last_name:  str
    full_name:  str
    position:   Optional[str] = None
    is_active:  bool = True


class RosterEntry(BaseModel):
    player_id:     int
    full_name:     str
    position:      Optional[str] = None
    jersey_number: Optional[str] = None


class SynergyRow(BaseModel):
    play_type:  str
    ppp:        Optional[float] = None
    efg_pct:    Optional[float] = None
    fg_pct:     Optional[float] = None
    tov_pct:    Optional[float] = None
    percentile: Optional[float] = None


# ---------------------------------------------------------------------------
# Data — possessions / shots / matchups
# ---------------------------------------------------------------------------

class Possession(BaseModel):
    possession_id:    int
    period:           int
    start_clock_s:    float
    end_clock_s:      float
    offense_team_id:  int
    defense_team_id:  int
    play_type:        Optional[str] = None
    play_type_source: Optional[str] = None
    outcome:          Optional[str] = None
    points:           int
    start_type:       Optional[str] = None
    video_url:        Optional[str] = None
    game_id:          Optional[str] = None  # populated by /possessions/search


class PossessionSearchRequest(BaseModel):
    season:           Optional[str] = None
    start_type:       Optional[str] = None
    outcome:          Optional[str] = None
    play_type:        Optional[str] = None
    play_type_source: Optional[str] = None
    offense_team_id:  Optional[int] = None
    defense_team_id:  Optional[int] = None
    min_points:       Optional[int] = None
    max_points:       Optional[int] = None
    has_video:        Optional[bool] = None
    limit:            int = Field(50, ge=1, le=500)
    offset:           int = Field(0,  ge=0)


class PossessionSearchResponse(BaseModel):
    total:   int
    limit:   int
    offset:  int
    results: list[Possession]


class Shot(BaseModel):
    event_id:        int
    player_id:       int
    team_id:         int
    period:          int
    action_type:     Optional[str] = None
    shot_type:       Optional[str] = None
    shot_zone_basic: Optional[str] = None
    shot_zone_area:  Optional[str] = None
    shot_distance:   Optional[float] = None
    loc_x:           Optional[float] = None
    loc_y:           Optional[float] = None
    made:            bool


class MatchupRow(BaseModel):
    game_id:             str
    defender_id:         int
    offender_id:         int
    matchup_minutes:     Optional[float] = None
    partial_possessions: Optional[float] = None
    player_points:       Optional[int]   = None
    matchup_fgm:         Optional[int]   = None
    matchup_fga:         Optional[int]   = None
    matchup_fg3m:        Optional[int]   = None
    matchup_fg3a:        Optional[int]   = None


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------

class LineupPredictRequest(BaseModel):
    player_ids: list[int] = Field(..., min_length=5, max_length=5)
    season:     str = "2023-24"


class LineupPredictResponse(BaseModel):
    predicted_net_rating: float
    season:               str
    player_ids:           list[int]


class MatchupPredictRequest(BaseModel):
    offense_ids: list[int] = Field(..., min_length=5, max_length=5)
    defense_ids: list[int] = Field(..., min_length=5, max_length=5)
    season:      str = "2023-24"


class MatchupPredictResponse(BaseModel):
    predicted_diff:       float
    offense_net_rating:   float
    defense_net_rating:   float
    season:               str


# ---------------------------------------------------------------------------
# Recommend
# ---------------------------------------------------------------------------

class PlayerRoleOut(BaseModel):
    player_id: int
    name:      str
    position:  Optional[str] = None
    role:      str
    ppp:       float
    action:    str


class WhiteboardPlayer(BaseModel):
    player_id: int
    name:      str
    position:  Optional[str] = None
    role:      str
    court_x:   float
    court_y:   float
    action:    str
    ppp:       float


class WhiteboardInstructions(BaseModel):
    play_type:   str
    diagram_key: str
    players:     list[WhiteboardPlayer]
    ball_start:  dict


class PlayRecommendation(BaseModel):
    rank:                    int
    play_type:               str
    display_name:            str
    predicted_ppp:           float
    confidence:              float
    method:                  str
    diagram_key:             str
    explanation:             str
    player_roles:            list[PlayerRoleOut]
    whiteboard_instructions: WhiteboardInstructions


class RecommendRequest(BaseModel):
    offense_ids: list[int] = Field(..., min_length=5, max_length=5)
    defense_ids: Optional[list[int]] = None
    top_n:       int = 3
    method:      str = "synergy"
    season:      str = "2023-24"


class RecommendResponse(BaseModel):
    season:          str
    method:          str
    recommendations: list[PlayRecommendation]


# ---------------------------------------------------------------------------
# Named plays (playbook)
# ---------------------------------------------------------------------------

class PlaySummary(BaseModel):
    play_id:     str
    name:        str
    family:      Optional[str] = None
    team:        Optional[str] = None
    season:      Optional[str] = None
    source_page: Optional[int] = None
    description: Optional[str] = None


class RoleAction(BaseModel):
    primary_action: str
    description:    Optional[str] = None


class PlayFrame(BaseModel):
    frame:       int
    description: Optional[str] = None
    players:     list[dict]    # [{role, x, y}]
    actions:     list[dict]    # heterogeneous; left as dicts for now


class PlayDetail(PlaySummary):
    role_actions: dict[str, RoleAction]
    shooters:     list[int]
    frames:       list[PlayFrame]


class PlayProbabilityRequest(BaseModel):
    offense_ids: list[int] = Field(..., min_length=5, max_length=5)
    defense_ids: Optional[list[int]] = Field(None, min_length=5, max_length=5)
    season:      str = "2024-25"


class PlayBreakdownRow(BaseModel):
    role:                int
    player_id:           int
    player_name:         str
    primary_action:      str
    ppp:                 float
    is_shooter:          bool
    weight:              float
    ppp_source:          str             = "synergy"   # synergy / shot_zone / blended / default
    sample_size:         Optional[int]   = None
    defender_id:         Optional[int]   = None
    defender_name:       Optional[str]   = None
    defender_adjustment: Optional[float] = None


class PlayProbabilityResponse(BaseModel):
    play_id:           str
    play_name:         str
    season:            str
    predicted_ppp:     float
    shooters_avg_ppp:  float
    lineup_avg_ppp:    float
    role_breakdown:    list[PlayBreakdownRow]
    notes:             list[str]
