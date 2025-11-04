from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import pointFunctions, stats

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# I've slightly increased the cutoff to a round number.
MAX_PLAYERS_ALL = 300
MAX_PLAYERS_FILTERED = 150

@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    position: str = Query(None, description="Filter by position"),
    scoring: str = Query("ppr", description="Scoring mode: ppr, half_ppr, standard")
):
    year, week = stats.get_current_season_week()

    # Fetch actual stats and projections
    week_stats_list = stats.get_week_stats(year, week, scoring_mode=scoring)["fantasy_stats"]
    week_stats = {entry["player"]: entry["points"] for entry in week_stats_list}
    sleeper_projs = stats.get_sleeper_projections(year, week) or {}
    players_metadata = stats.get_player_metadata() or {}

    ALLOWED_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}
    all_players = [] # This list will hold ALL players, for the frontend search

    for pid, meta in players_metadata.items():
        pos = meta.get("position", "N/A")
        if pos not in ALLOWED_POSITIONS:
            continue

        name = f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip()
        team = meta.get("team", "FA")
        week_points = week_stats.get(name, 0)

        # Sleeper projection
        proj_stats = sleeper_projs.get(pid, {})
        sleeper_proj = proj_stats.get("pts_ppr") or proj_stats.get("fantasy_points_ppr") or 0
        if sleeper_proj == 0:
            sleeper_proj = pointFunctions.calculate_points(proj_stats.get("stats", {}), pos, scoring_mode=scoring)

        avg_pts = stats.average_projections(sleeper_proj)

        all_players.append({
            "name": name,
            "position": pos,
            "team": team,
            "week_points": week_points,
            "sleeper_projection": sleeper_proj,
            "average": avg_pts
        })
    
    # Sort the complete list once. This list will be sent to the frontend for search functionality.
    all_players.sort(key=lambda x: x["average"], reverse=True)

    # Now, create the list for initial display, applying the position filter.
    players_to_display = all_players
    if position:
        players_to_display = [p for p in all_players if p["position"].upper() == position.upper()]
    
    # Apply the cutoff for the display list.
    if position:
        players_to_display = players_to_display[:MAX_PLAYERS_FILTERED]
    else:
        players_to_display = players_to_display[:MAX_PLAYERS_ALL]

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "players": players_to_display,
            "year": year,
            "week": week,
            "selected_position": position or "",
            "selected_scoring": scoring,  # Pass selected scoring mode to template
            "all_players": all_players
        }
    )