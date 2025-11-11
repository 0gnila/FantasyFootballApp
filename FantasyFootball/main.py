# main.py
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pymongo import MongoClient
import stats
import rag  # Import your new RAG file
import os
from collections import defaultdict

# Load .env file
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

# --- MongoDB Connection ---
print("Connecting to MongoDB...")
client = MongoClient(MONGO_URI)
db = client["fantasy_football"]
players_collection = db["players"]
print("✅ Connected to MongoDB.")

# --- FastAPI App ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")
# Mount a 'static' directory (optional, but good practice)
# app.mount("/static", StaticFiles(directory="static"), name="static")

MAX_PLAYERS_ALL = 300
MAX_PLAYERS_FILTERED = 150

@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    position: str = Query(None, description="Filter by position"),
    scoring: str = Query("ppr", description="Scoring mode: ppr, half_ppr, standard"),
    week: int = Query(None, description="Select a specific week (1-18)")
):
    year, current_api_week = stats.get_current_season_week()
    
    # Use the user-selected week if provided, otherwise default to the current week
    selected_week = week if week is not None and 1 <= week <= 18 else current_api_week

    print(f"📅 Loading data for Year {year}, Week {selected_week} ({scoring})")

    # --- THE FIX: ONE QUERY ---
    # Fetch all stats for the entire season for this scoring mode
    all_season_stats = list(players_collection.find({
        "year": year, 
        "scoring_mode": scoring
    }))

    if not all_season_stats:
        print("⚠️ No data found in DB for this season/scoring mode.")
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request, "players": [], "year": year, "week": selected_week,
                "current_api_week": current_api_week, "selected_position": position or "",
                "selected_scoring": scoring, "all_players": [],
            },
        )

    # --- Process all data in memory (fast) ---
    player_totals = defaultdict(lambda: {"total_points": 0.0, "weeks_played": 0})
    week_stats_map = {}
    player_metadata = {} # Stores name, pos, team from first entry

    for entry in all_season_stats:
        name = entry.get("player")
        if not name:
            continue

        # Store metadata (we only need one entry per player)
        if name not in player_metadata:
            player_metadata[name] = entry

        # Add to season average calculation
        player_totals[name]["total_points"] += entry.get("points", 0)
        player_totals[name]["weeks_played"] += 1 # One doc = one week played
            
        # If this entry is for the user's selected week, save its points
        if entry.get("week") == selected_week:
            week_stats_map[name] = entry.get("points", 0)

    # --- Build the final player list ---
    ALLOWED_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}
    all_players = []

    for name, meta in player_metadata.items():
        pos = meta.get("position", "N/A")
        if pos not in ALLOWED_POSITIONS:
            continue

        totals = player_totals[name]
        avg_pts = (totals["total_points"] / totals["weeks_played"]) if totals["weeks_played"] > 0 else 0.0

        all_players.append({
            "name": name,
            "position": pos,
            "team": meta.get("team", "FA"),
            "week_points": week_stats_map.get(name, 0), # Get the specific week's points
            "sleeper_projection": 0, # This data isn't being pulled yet
            "average": avg_pts,
        })

    # Sort and filter (same as before)
    all_players.sort(key=lambda x: x["average"], reverse=True)
    players_to_display = [p for p in all_players if not position or p["position"].upper() == position.upper()]
    players_to_display = players_to_display[:MAX_PLAYERS_FILTERED if position else MAX_PLAYERS_ALL]

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "players": players_to_display,
            "year": year,
            "week": selected_week,
            "current_api_week": current_api_week,
            "selected_position": position or "",
            "selected_scoring": scoring,
            "all_players": all_players,
        },
    )

# --- AI Assistant Routes ---
# ... (keep your /ai and /ask routes exactly as they are) ...

@app.get("/ai", response_class=HTMLResponse)
def ai_page(request: Request):
    """Serves the main page for the AI assistant."""
    year, week = stats.get_current_season_week()
    return templates.TemplateResponse("ai.html", {
        "request": request, 
        "question": "", 
        "answer": "",
        "year": year,
        "week": week,
        "scoring": "ppr"
    })

@app.get("/ask", response_class=HTMLResponse)
def ask(
    request: Request, 
    q: str = Query(..., description="The user's question"),
    year: int = Query(...),
    week: int = Query(...),
    scoring: str = Query(...)
):
    """Handles the question from the AI assistant form."""
    print(f"AI Query: {q} (Week {week}, {scoring})")
    answer = rag.ask_gemini(q, year, week, scoring)
    return templates.TemplateResponse("ai.html", {
        "request": request,
        "question": q,
        "answer": answer,
        "year": year,
        "week": week,
        "scoring": scoring
    })

import ai_agent

@app.get("/ask-agent", response_class=HTMLResponse)
def ask_agent_endpoint(
    request: Request, 
    q: str = Query(..., description="The user's question")
):
    """Handles questions for the new, smarter AI agent."""
    print(f"Agent Query: '{q}'")
    answer = ai_agent.ask_agent(q)
    
    # We still need the current week info to render the template
    year, current_api_week = stats.get_current_season_week()

    # We can reuse the same ai.html template
    return templates.TemplateResponse("ai.html", {
        "request": request,
        "question": q,
        "answer": answer,
        "year": year,
        "week": current_api_week, # Default the dropdown to the latest week
        "current_api_week": current_api_week,
        "scoring": "ppr"
    })