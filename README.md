# ball_up_top

# NBA Analytics Platform

ML-powered play recommendation engine with a 5-layer SQLite warehouse, two
ingestion paths (bulk archive + `nba_api`), a FastAPI service, and an
interactive whiteboard renderer.

---

## Architecture overview

```
        ┌─────────────────────────┐ ┌──────────────────────┐ ┌────────────────────────┐
        │  bulk archive (.tar.xz) │ │       nba_api        │ │   PDF playbook + .yaml │
        │  shufinskiy/nba_data    │ │  (live stats.nba.com)│ │  (CNN model)           │
        └──────────┬──────────────┘ └──────────┬───────────┘ └──────────┬─────────────┘
                   │                           │                        │
                   ▼                           ▼                        ▼
            ingestion/ingest_bulk       ingestion/ingest_*       ingestion/extract_plays
            (PBP, possessions,         (reference, analytics,    →  plays/<team>/*.yaml
             tracking, shots, matchups) game catch-up)            ingestion/load_plays
                   │                           │                        │
                   └───────────────────┬───────┴────────────────────────┘
                                       ▼
                              db/nba_platform.db (SQLite)
                                       │
                       ┌───────────────┼────────────────┬─────────────────┐
                       ▼               ▼                ▼                 ▼
               ml/features.py   ingestion/derive_*   data queries   ml/play_probability
                       │               │                 │                 │
                       ▼               ▼                 │                 │
               ml/lineup_model      possession           │                 │
               ml/play_recommender   events              │                 │
                       │                                 │                 │
                       └─────────────────┬───────────────┴─────────────────┘
                                         ▼
                                    api/ (FastAPI)
                                         │
                                         ▼
                               frontend/whiteboard.html
```

---

## Project structure

```
nba_platform/
├── db/
│   ├── schema.sql          # 19-table SQLite DDL (5 layers + shot_charts + player_matchups)
│   ├── database.py         # Connection mgr, upserts, replace_* helpers, idempotent migrations
│   └── nba_platform.db     # Live database (gitignored — regenerate via init_db)
│
├── ingestion/
│   ├── utils.py            # rate_limited_call, parse_clock, make_lineup_key, Checkpoint
│   ├── ingest_bulk.py      # PRIMARY: 5 adapters reading data/bulk/*.tar.xz
│   ├── ingest_reference.py # nba_api: teams + players + rosters (~30s/season)
│   ├── ingest_analytics.py # nba_api: synergy + lineup_stats + season stats (~30s/season)
│   ├── ingest_games.py     # nba_api: --since delta mode, or per-team backfill
│   ├── ingest_sportvu.py   # SportVU JSON → tracking_moments (2015-16 only)
│   ├── derive_lineups.py   # Stints from PBP starters + subs; back-fills possession lineup_keys
│   └── derive_possessions.py # Possession state machine; skips when pbpstats data exists (--force overrides)
│
├── ml/
│   ├── features.py         # FeatureStore: player → lineup feature vectors (152-dim)
│   ├── lineup_model.py     # XGBoost NET_RATING predictor
│   ├── play_recommender.py # Play type recommender + whiteboard_instructions builder
│   └── saved_models/       # Persisted .pkl artifacts (gitignored)
│
├── api/
│   ├── main.py             # FastAPI app, lifespan, CORS, router includes
│   ├── deps.py             # DI: get_db, cached FeatureStore/Recommender per season
│   ├── schemas.py          # Pydantic request/response models
│   └── routers/
│       ├── reference.py    # /teams, /players, /players/{id}/synergy
│       ├── data.py         # /games/{id}/possessions, /shots, /players/{id}/matchups
│       ├── prediction.py   # /lineup/predict, /matchup/predict
│       └── recommend.py    # /plays/recommend
│
├── plays/
│   ├── _taxonomy.yaml      # Structured play-pattern glossary (rendered into the extractor's system prompt)
│   ├── <team>/             # 29 NBA team directories (2018-19) + LAL 2022-23, 1,006 YAMLs total
│   └── .extraction/        # Per-page raw model JSONs (gitignored — debug only)
│
├── tests/                  # 222 tests (platform + ml + api + bulk + derived + delta + plays)
├── frontend/whiteboard.html # Self-contained SVG court renderer
├── data/
│   ├── bulk/               # Drop .tar.xz archives here (gitignored)
│   ├── playbook/           # Drop PDF playbooks here (gitignored)
│   └── sportvu/            # Optional 2015-16 spatial tracking
├── checkpoints/            # JSON resume files for long ingestion runs
├── logs/                   # Extraction run logs (gitignored)
├── conftest.py             # Puts project root on sys.path for pytest
├── start.py                # Local-app launcher: uvicorn + auto-open browser
├── start.bat               # Windows double-click wrapper around start.py
├── requirements.txt
└── README.md
```

---

## Database schema — 5 layers + 2 bulk-only tables

| Layer | Tables | Purpose |
|-------|--------|---------|
| L1 Reference | `teams`, `players`, `rosters` | Slow-changing master data |
| L2 Game & Events | `games`, `play_by_play`, `game_lineups` | Per-game event spine |
| L3 Tracking | `tracking_moments`, `possession_events` | Spatial + possession data |
| L4 Analytics | `lineup_stats`, `synergy_play_types`, `pass_tracking`, `player_season_stats` | ML feature inputs |
| L4+ Bulk | **`shot_charts`**, **`player_matchups`** | Per-shot zones, defender splits |
| L5 Video Pipeline | `video_clips`, `video_frames`, `video_detections`, `video_player_positions` | Future video extraction path |

**Source discrimination columns** make every downstream consumer source-agnostic:
- `tracking_moments.source` ∈ {`sportvu`, `data_nba_event`, `video_extracted`, `synthetic`}
- `possession_events.play_type_source` ∈ {`pbpstats`, `pbp_inferred`, `synergy`, `video_classified`, `manual`}
- `possession_events.start_type` carries pbpstats's possession-context label (`Off Steal`, `Off Timeout`, etc.)

**Source precedence:** when `derive_possessions.py` runs on a game that already has
pbpstats-sourced possessions, it skips that game (pbpstats is the better source). Use
`--force` to overwrite. When `derive_lineups.py` runs after bulk ingestion, it
back-fills `offense_lineup_key` / `defense_lineup_key` on existing pbpstats possessions
in a single UPDATE pass.

The `lineup_key` (sorted player IDs joined by `-`) is the join key between
`game_lineups`, `lineup_stats`, and `possession_events`.

---

## Ingestion paths — when to use which

| Need | Path | Time/season | Source |
|---|---|---|---|
| PBP, possessions, tracking, shots, matchups | `ingest_bulk.py` | **~38s** | bulk archive |
| Teams, players, rosters (full bios) | `ingest_reference.py` | ~30s | nba_api |
| Synergy PPP, lineup_stats, player_season_stats | `ingest_analytics.py` | ~30s | nba_api |
| Recent games not in bulk (delta) | `ingest_games.py --since auto` | ~10s + ~1s/game | nba_api |
| Single-team historical backfill (legacy) | `ingest_games.py --team-id` | ~hours/team | nba_api |
| 2015-16 SportVU spatial tracking | `ingest_sportvu.py` | minutes | local JSON files |

The bulk archive is sourced from `github.com/shufinskiy/nba_data` (Apache-2.0,
free) and covers 1996-97 onward. Drop `.tar.xz` files into `data/bulk/`.

`nba_api` itself costs **$0** (free Python library hitting public
stats.nba.com endpoints) but is unofficial — rate-limited at ~100 req/min and
subject to NBA-side changes.

---

## ML layer

### Feature assembly (`ml/features.py`)

**Per-player features (19):**
- 10 × Synergy PPP by play type (PRBallHandler, Isolation, Spotup, etc.)
- 8 × season stats (pts_pg, reb_pg, ast_pg, fg_pct, fg3_pct, ts_pct, usg_pct, def_rating)
- 1 × position encoding (G=0, F=1, C=2)

**Per-lineup features (76):** mean/std/max/min × 19 player features
**Model input (152):** offense lineup features (76) + defense lineup features (76)

### Model 1 — Lineup efficiency (`ml/lineup_model.py`)
XGBoost regressor with StandardScaler pipeline, RandomizedSearchCV (20 iter, 5-fold CV)
predicting `NET_RATING`. Save/load via pickle.

### Model 2 — Play recommender (`ml/play_recommender.py`)
- **Synergy mode** (default): ranks play types by aggregated PPP — works as soon as `ingest_analytics.py` has run.
- **Model mode**: GradientBoosting on `possession_events`. Now usable since `ingest_bulk.py pbpstats` populates ~243k possessions per season.

Output includes structured `whiteboard_instructions` consumed by the diagram renderer.

---

## FastAPI service

### Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/teams` | All 30 teams |
| GET | `/teams/{team_id}/roster?season=` | Needs `ingest_reference.py` |
| GET | `/players?search=&limit=` | Autocomplete |
| GET | `/players/{player_id}` | |
| GET | `/players/{player_id}/synergy?season=` | Needs `ingest_analytics.py` |
| GET | `/players/{player_id}/matchups?role=defender|offender&top_n=` | Bulk-fed |
| GET | `/games/{game_id}/possessions?period=` | Bulk-fed (pbpstats) |
| GET | `/games/{game_id}/shots?player_id=` | Bulk-fed (shotdetail) |
| POST | `/possessions/search` | Slice 486k+ possessions by season / start_type / outcome / play_type / points / has_video |
| POST | `/lineup/predict` | Returns 503 until model trained + saved |
| POST | `/matchup/predict` | Same |
| POST | `/plays/recommend` | Synergy mode works once analytics ingested |

### Run

**One-click (recommended for local use):**

```bash
# Windows: just double-click start.bat
# or from a shell:
py -3.14 start.py
```

That launches `uvicorn` on `http://localhost:8000`, opens the whiteboard in your default browser as soon as the port is up, and prints request logs to the console. `Ctrl-C` stops it. The FastAPI app serves [frontend/whiteboard.html](frontend/whiteboard.html) at `/` and exposes the same JSON endpoints under `/teams`, `/players`, `/plays`, etc.

**Manual (for development with auto-reload):**

```bash
uvicorn api.main:app --reload
# Auto-generated docs at http://localhost:8000/docs
```

CORS is open (`*`) so the whiteboard works either when served by FastAPI (same origin) or when opened as a `file://` page. Tighten before deploying.

---

## Named-play library (`plays/`)

The `plays/` directory holds YAML definitions of NBA plays — one file per play, organized by team. Each play maps each of the 5 offensive roles to a Synergy-taxonomy action (`Spotup`, `OffScreen`, `PRBallHandler`, etc.) and lists the frames showing player positions and movements.

**Current corpus: 1,006 plays loaded across 29 NBA teams + the 2022-23 Lakers** — extracted via the multimodal pipeline (see below) from the 2018-19 league-wide playbook (874 plays) and the captioned 2022-23 Lakers playbook (132 plays). Memphis is the lone gap — the source PDF skips that team. The structured play-pattern primitives that informed extraction live in [plays/_taxonomy.yaml](plays/_taxonomy.yaml) and are rendered into the extractor's system prompt at module load.

The `PlayProbabilityEstimator` ([ml/play_probability.py](ml/play_probability.py)) blends multiple sources to estimate a lineup's expected PPP for any play:

| Tier | Source | When it wins |
|---|---|---|
| **A. Synergy PPP** | `synergy_play_types` | Default for non-shooting actions |
| **B. Shot-zone PPP** | `shot_charts` (zone-aware) | When the role's action is shot-shaped (Spotup, OffScreen, Cut, Postup, OffRebound) AND the player has ≥30 shots in those zones for the season |
| **2. Defender adjustment** | `player_matchups` | When `defense_ids` is provided |

Each role's response includes `ppp_source` and `sample_size` so the UI can show users *which* data fed the rating.

### Loading hand-authored plays

```bash
python -m ingestion.load_plays                     # load every plays/**/*.yaml
python -m ingestion.load_plays --strict             # fail fast on validation errors
```

The extractor handles two playbook styles:
- **Captioned books** (e.g. 2022-23 Lakers): plain-English captions sit beneath each diagram. The prompt treats the caption as ground truth and uses it to assign every action's `actor_role` / `target_role`.
- **Captionless books** (e.g. 2018-19 NBA full-team set): the model relies on visual cues + the play title. Title primitives (Pin Down, Stagger, Zipper, Chicago, etc.) are matched against [plays/_taxonomy.yaml](plays/_taxonomy.yaml) — a structured glossary of canonical action patterns — to pick the right `screen_for` / `cut` / `handoff_to` shape.

The taxonomy file is the **single source of truth** for the glossary: `extract_plays.py` renders it into `SYSTEM_PROMPT` at module load, so editing the YAML updates the prompt with no code change.

```bash
export ANTHROPIC_API_KEY=...

# Sanity-check on a small range first
python -m ingestion.extract_plays --pdf playbook.pdf --pages 1-10

# Inspect the writes under plays/<team>/, then full run
python -m ingestion.extract_plays --pdf playbook.pdf --resume

# Then validate + load
python -m ingestion.load_plays
```

Flags:
- `--pages 1-50` / `--pages 1,3,5-9` / `--pages all`
- `--resume` skips pages already in `plays/.extraction/page_NNNN.json`
- `--max-cost 5` stops early at $5 of API spend
- `--dry-run` renders pages but doesn't call the API
- `--model claude-sonnet-4-6` for a cheaper model

Raw model responses go to `plays/.extraction/page_NNNN.json` for human review; validation errors go to `plays/.extraction/page_NNNN.errors.txt`. Files starting with `_` (e.g. `_taxonomy.yaml`) are skipped by `load_plays` — that's the meta-file convention.

#### Extending the play taxonomy

To add a new primitive (e.g. "Spain", "Iverson", "Horns Twist"), append an entry to [plays/_taxonomy.yaml](plays/_taxonomy.yaml) with:
- `name` and `aliases` for title-matching
- `description` prose for the model
- `primary_actions` mapping role-archetype → Synergy action
- `actions` list — the canonical `{actor, type, target}` shapes

The next extraction run picks it up automatically. The structured form is also designed for future consumers: post-extraction validators (flag plays whose actions don't match the named primitive), play clustering for the recommender, and UI tooltips.

---

## Quick start — one season, end-to-end

Drop the season's `.tar.xz` files into `data/bulk/`, then:

```bash
pip install -r requirements.txt

# Bulk: PBP, possessions, tracking, shots, matchups (~38s)
python -m ingestion.ingest_bulk --dataset all --season 2024-25

# nba_api: rosters + bios (~30s)
python -m ingestion.ingest_reference --season 2024-25

# nba_api: synergy + lineup_stats + season stats (~30s; pass tracking opt-in via --passes)
python -m ingestion.ingest_analytics --season 2024-25

# Derive stints from PBP and back-fill lineup keys onto pbpstats possessions
python -m ingestion.derive_lineups --season 2024-25

# Train + save the lineup efficiency model (~10s)
python -m ml.lineup_model --season 2024-25

# Load the named-play library (1,006 YAMLs already in plays/<team>/) into the DB (~10s)
python -m ingestion.load_plays

# Serve
uvicorn api.main:app --reload
```

**Total: ~2 minutes** for a fully-populated, model-loaded API serving real data.

### Daily catch-up

```bash
# Fetches any league-wide games newer than the DB's MAX(game_date)
python -m ingestion.ingest_games --since auto --season 2024-25
```

### Get bulk archives

```bash
# URL pattern: https://github.com/shufinskiy/nba_data/raw/main/datasets/{name}_{year}.tar.xz
# Where {name} ∈ {nbastatsv3, pbpstats, datanba, shotdetail, matchups}
# And {year} is the starting year of the season (2024 == 2024-25)
```

---

## Run tests

```bash
python -m pytest tests/ -v        # 222 tests, ~30s
python -m pytest tests/test_api.py -v
python -m pytest tests/test_bulk.py -v
```

Test breakdown:
- `test_platform.py` — schema, DB upserts, utils, ingestion logic, delta-mode helpers
- `test_ml.py` — features, lineup model, recommender, edge cases
- `test_derived.py` — lineup + possession derivers (state machine, pbpstats precedence, lineup back-fill)
- `test_bulk.py` — 5 adapters via synthetic `.tar.xz`, idempotency, schema migration
- `test_api.py` — FastAPI TestClient against seeded fixture DB (incl. `/possessions/search`)

---

## Data sources

| Source | Access | What it provides |
|--------|--------|-----------------|
| `shufinskiy/nba_data` | Free, GitHub `.tar.xz` (Apache-2.0) | Bulk PBP, possessions, tracking, shots, matchups (1996-present) |
| `nba_api` | Free, Python library | Synergy PPP, season aggregates, rosters, current-season catch-up |
| `neilmj/BasketballData` | Free, GitHub | SportVU spatial tracking (2015-16 only) |
| NBA League Pass | Paid subscription | Video for the future L5 extraction pipeline |

---

## What's been built

### Storage + ingestion
- [x] 19-table SQLite schema with idempotent column migrations and view-recreate-on-init
- [x] DB layer with upsert / replace / bulk-insert helpers
- [x] **Bulk ingestion (5 adapters, ~38s/season)** — PBP, possessions, tracking, shots, matchups
- [x] **`nba_api` ingestion** — reference (rosters/bios, NaN-safe), analytics (synergy + lineup_stats + season stats; pass tracking opt-in), `--since` league-wide game delta
- [x] SportVU JSON parser (`SportVUGame` class)

### Derivers
- [x] Lineup deriver (stints from PBP starters + substitutions)
- [x] **Possession deriver with pbpstats precedence** — heuristic state machine that auto-defers to pbpstats data when present; `--force` to override
- [x] **Lineup back-fill** — `derive_lineups` updates pbpstats possessions with offense/defense lineup_keys in a single UPDATE pass after writing stints

### ML
- [x] Feature store (player → lineup feature vectors, NaN-safe)
- [x] Lineup efficiency model (XGBoost, CV, save/load) with one-command CLI: `python -m ml.lineup_model --season ...`
- [x] Play recommender (synergy + model modes, role assignment, whiteboard output)

### Service + UI
- [x] **FastAPI service (12 endpoints)** with model lifespan, CORS, OpenAPI docs
- [x] **`POST /possessions/search`** — filter 486k+ possessions by season / start_type / outcome / play_type / team / points range / has_video, with pagination
- [x] **Interactive whiteboard wired to the API** — `fetch('/plays/recommend', …)` with editable lineup IDs, season, top-N, and live error / loading states

### Play library + probability estimator
- [x] **YAML play schema** — one file per play, role-keyed Synergy actions, multi-frame diagrams, validated by `ingestion/load_plays.py`
- [x] **Multimodal PDF extractor** — `ingestion/extract_plays.py` reads PDF playbooks via Claude Opus 4.7 vision, handles captioned + captionless layouts, multi-play pages (Lakers-style), and "(N/M)"-stitched multi-frame plays
- [x] **Structured play-pattern taxonomy** — [plays/_taxonomy.yaml](plays/_taxonomy.yaml) with 13 primitives (Pin Down, Stagger, Zipper, Chicago, DHO, Ghost, UCLA, Ram, Punch, Drag, Flare, Floppy, Cross Screen) rendered into the extractor's system prompt at module load
- [x] **Two playbooks fully ingested** — 132 plays from the 2022-23 Lakers playbook (captioned ground truth) + 874 plays from the 2018-19 league-wide playbook (captionless, Lakers-prompt-informed). **1,006 total plays in the DB across 29 NBA teams + LAL 2022-23. Zero validation errors.** MEM is absent — the source PDF skips that team. Total extraction spend across all runs: ~$14 over 934 PDF pages.
- [x] **Per-team coverage** — varies with each coach's published playbook depth. Densest: LAL 165, OKC 137, HOU 77, LAC 67, DEN 65, UTA 58, BOS 52, DET 47, TOR 45, BKN 37. Thinnest (likely thin in source PDF): CHA 2, MIN 3, NOP 6, CHI 6, CLE 6, PHX 6.
- [x] **`PlayProbabilityEstimator`** — Tier-A Synergy PPP → Tier-B shot-zone PPP (blended/shrunk by sample size) → defender adjustment waterfall, exposed via `/plays/{id}/probability`

### Quality
- [x] **222 passing tests** across 6 modules (incl. 26 plays-specific tests covering validation, the tier waterfall, and the API)

---

## Further improvements — ranked by leverage

### High-value, ambitious
1. **Tracking-based play_type classifier** — train a model on the SportVU / datanba moments
   to classify possessions into the Synergy taxonomy. Would close the only remaining hard
   dependency on `nba_api` (Synergy PPP) and let the heuristic deriver tag pbpstats
   possessions with proper play types.
2. **Derive `lineup_stats` and `player_season_stats` from bulk** — aggregate from
   `possession_events` + `shot_charts` + `play_by_play`. Removes the analytics dependency
   on `nba_api` entirely (Synergy stays the long pole).
3. **Data freshness dashboard / endpoint** — track per-table `MAX(created_at)` and
   per-source ingestion timestamps; expose via `/admin/freshness`. Catches bulk-archive
   staleness early.

### Medium-value, low-effort polish
4. **Run `derive_lineups --season 2024-25` for the whole season** — back-fills all ~243k
   pbpstats possessions in one shot (currently only games processed individually have lineup
   keys attached).
5. **Use the matchup model in `/plays/recommend?method=model`** — `possession_events` is
   populated and `FeatureStore.build_matchup_data()` can now train. ~1 minute per season.
6. **Smarter player-name handling on bulk ingest** — currently we rely on
   `ingest_reference.py` to overwrite stubs after the fact. Could detect single-token
   names and queue the player ID for a targeted re-fetch, or just skip the stub if a real
   row exists.

### Future / blocked
- Video extraction pipeline (L5: OpenCV frame extraction, YOLO detection, homography)
- React dashboard (wire frontend to FastAPI beyond the whiteboard)
- Redshift migration (swap SQLite for production-scale storage)
