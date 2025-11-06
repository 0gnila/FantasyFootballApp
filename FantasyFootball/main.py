from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timedelta
import pointFunctions, stats
import os

# Load .env file
load_dotenv()

# Access environment variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

# --- MongoDB Connection ---
print("Connecting to MongoDB...")
client = MongoClient(MONGO_URI)
try:
    print("✅ Connected! Databases:", client.list_database_names())
except Exception as e:
    print("❌ Mongo connection failed:", e)

db = client["fantasy_football"]
players_collection = db["players"]

# --- FastAPI App ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")

MAX_PLAYERS_ALL = 300
MAX_PLAYERS_FILTERED = 150
REFRESH_INTERVAL = timedelta(hours=24)  # Auto-update once a day

@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    position: str = Query(None, description="Filter by position"),
    scoring: str = Query("ppr", description="Scoring mode: ppr, half_ppr, standard")
):
    year, week = stats.get_current_season_week()
    print(f"📅 Loading data for Year {year}, Week {week} ({scoring})")

    # Fetch player data (from MongoDB or Sleeper API)
    week_stats_list = get_player_data(year, week, scoring)

    ALLOWED_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}
    all_players = []

    for entry in week_stats_list:
        pos = entry.get("position", "N/A")
        if pos not in ALLOWED_POSITIONS:
            continue

        name = entry.get("player", "Unknown")
        team = entry.get("team", "FA")
        week_points = entry.get("points", 0)  # This is ONLY this week's points

        # Compute average across all weeks played
        avg_pts = stats.compute_player_season_average(name, year, scoring, players_collection)

        all_players.append({
            "name": name,
            "position": pos,
            "team": team,
            "week_points": week_points,  # CURRENT WEEK ONLY
            "sleeper_projection": entry.get("stats", {}).get("pts_ppr", 0),
            "average": avg_pts,  # SEASON AVERAGE
    })

    # Sort and filter
    all_players.sort(key=lambda x: x["average"], reverse=True)
    players_to_display = [p for p in all_players if not position or p["position"].upper() == position.upper()]
    players_to_display = players_to_display[:MAX_PLAYERS_FILTERED if position else MAX_PLAYERS_ALL]

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "players": players_to_display,
            "year": year,
            "week": week,
            "selected_position": position or "",
            "selected_scoring": scoring,
            "all_players": all_players,
        },
    )


def get_player_data(year, current_week, scoring):
    """
    Fetch stats from MongoDB for all weeks in the current season.
    If missing, fetch from Sleeper and store them.
    Then compute each player's season average up to current_week.
    """
    print(f"📅 Loading data for weeks 1–{current_week} ({scoring})...")
    all_week_stats = []

    for week in range(1, current_week + 1):
        docs = list(players_collection.find({"year": year, "week": week, "scoring_mode": scoring}))
        if not docs:
            print(f"📭 Week {week} not found in MongoDB — fetching from Sleeper API.")
            week_stats = stats.get_week_stats(year, week, scoring_mode=scoring)
            week_stats_list = week_stats.get("fantasy_stats", [])
            for p in week_stats_list:
                p.update({
                    "year": year,
                    "week": week,
                    "scoring_mode": scoring,
                    "last_updated": datetime.utcnow()
                })
            if week_stats_list:
                players_collection.insert_many(week_stats_list)
                print(f"🗃️ Cached {len(week_stats_list)} players for week {week}.")
            docs = week_stats_list
        all_week_stats.extend(docs)

    # --- 🧮 Compute average points across all available weeks ---
    player_totals = {}
    for entry in all_week_stats:
        name = entry.get("player", "Unknown")
        points = entry.get("points", 0)
        if name not in player_totals:
            player_totals[name] = {"total_points": 0, "weeks": 0, "meta": entry}
        if points > 0:
            player_totals[name]["total_points"] += points
            player_totals[name]["weeks"] += 1

    season_players = []
    for name, data in player_totals.items():
        weeks_played = data["weeks"]
        avg_points = round(data["total_points"] / weeks_played, 2) if weeks_played > 0 else 0
        entry = data["meta"]
        season_players.append({
            "player": name,
            "position": entry.get("position", "N/A"),
            "team": entry.get("team", "FA"),
            "points": data["total_points"],
            "average": avg_points,
            "weeks_played": weeks_played,
        })

    print(f"✅ Computed averages for {len(season_players)} players through Week {current_week}.")
    return season_players