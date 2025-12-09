from fastapi import FastAPI, Request, Query, Form, Depends, HTTPException, status, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv
from pymongo import MongoClient
import stats
import ai_agent
import auth
import os
from collections import defaultdict
from datetime import datetime

# Load .env file
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

# --- MongoDB Connection ---
print("Connecting to MongoDB...")
client = MongoClient(MONGO_URI)
db = client["fantasy_football"]
players_collection = db["players"]
users_collection = db["users"]
ai_logs_collection = db["ai_logs"]
print("Connected to MongoDB.")

app = FastAPI()
templates = Jinja2Templates(directory="templates")


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- Helper: Get Current User from Cookie ---
def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return None
    # Remove "Bearer " prefix if present (common in standard headers, less common in cookies but good safety)
    if token.startswith("Bearer "):
        token = token.split(" ")[1]
    
    username = auth.decode_token(token)
    if not username:
        return None
        
    user = users_collection.find_one({"username": username})
    return user

# --- Routes: Auth ---

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
def register(username: str = Form(...), password: str = Form(...)):
    if users_collection.find_one({"username": username}):
        return HTMLResponse("Username already exists", status_code=400)
    
    hashed_password = auth.get_password_hash(password)
    users_collection.insert_one({
        "username": username,
        "password": hashed_password,
        "team": [] # Initialize empty team
    })
    return RedirectResponse(url="/login", status_code=303)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(response: Response, username: str = Form(...), password: str = Form(...)):
    user = users_collection.find_one({"username": username})
    if not user or not auth.verify_password(password, user["password"]):
        return HTMLResponse("Incorrect username or password", status_code=401)
    
    access_token = auth.create_access_token(data={"sub": username})
    
    # Set cookie
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return response

@app.get("/logout")
def logout(response: Response):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("access_token")
    return response

# --- Routes: My Team ---

@app.get("/team", response_class=HTMLResponse)
def team(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    user_team = user.get("team", [])
    year, week = stats.get_current_season_week()
    enriched_team = []
    
    for player_obj in user_team:
        player_name = player_obj.get('name')
        if not player_name: continue
        
        # FIX 1 & 2: Get only 'ppr' games where points are strictly > 0
        # This ignores weeks they sat out (injury/bye) and ignores duplicates
        played_games = list(players_collection.find({
            "year": year, 
            "player": player_name,
            "scoring_mode": "ppr", 
            "points": {"$gt": 0} 
        }))
        
        total_points = sum(p['points'] for p in played_games)
        games_count = len(played_games)
        
        # Now the average divides ONLY by games actually played
        average = (total_points / games_count) if games_count > 0 else 0.0
        
        enriched_team.append({
            "name": player_name,
            "position": player_obj.get('position', 'N/A'),
            "average_points": round(average, 2),
            "games_played": games_count # Optional: Helpful to see
        })

    return templates.TemplateResponse("team.html", {
        "request": request, 
        "user": user,
        "team": enriched_team,
        "year": year, 
        "week": week
    })

@app.post("/add-player")
def add_player(request: Request, player_name: str = Form(...), position: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Avoid duplicates
    current_team = user.get("team", [])
    if not any(p['name'] == player_name for p in current_team):
        users_collection.update_one(
            {"_id": user["_id"]},
            {"$push": {"team": {"name": player_name, "position": position}}}
        )
    
    return RedirectResponse(url="/team", status_code=303)

@app.post("/remove-player")
def remove_player(request: Request, player_name: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
        
    users_collection.update_one(
        {"_id": user["_id"]},
        {"$pull": {"team": {"name": player_name}}}
    )
    return RedirectResponse(url="/team", status_code=303)


# --- Routes: Core ---

@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    position: str = Query(None),
    scoring: str = Query("ppr"),
    week: int = Query(None)
):
    user = get_current_user(request)
    year, current_api_week = stats.get_current_season_week()
    selected_week = week if week is not None and 1 <= week <= 18 else current_api_week

    # Fetch stats (same logic as before)
    all_season_stats = list(players_collection.find({
        "year": year, 
        "scoring_mode": scoring
    }))

    # ... [Keeping your existing logic for processing stats] ...
    # (Simplified for brevity here, assuming you copy the logic from your old main.py 
    # for processing 'all_season_stats' into 'players_to_display')
    
    # Reuse your existing stats processing code here
    # For now, I'll put a placeholder logic to ensure it runs
    player_totals = defaultdict(lambda: {"total_points": 0.0, "weeks_played": 0})
    week_stats_map = {}
    player_metadata = {}

    for entry in all_season_stats:
        name = entry.get("player")
        if not name: continue
        if name not in player_metadata: player_metadata[name] = entry
        player_totals[name]["total_points"] += entry.get("points", 0)
        player_totals[name]["weeks_played"] += 1
        if entry.get("week") == selected_week:
            week_stats_map[name] = entry.get("points", 0)

    all_players = []
    for name, meta in player_metadata.items():
        pos = meta.get("position", "N/A")
        totals = player_totals[name]
        avg_pts = (totals["total_points"] / totals["weeks_played"]) if totals["weeks_played"] > 0 else 0.0
        all_players.append({
            "name": name, "position": pos, "team": meta.get("team", "FA"),
            "week_points": week_stats_map.get(name, 0), "average": avg_pts,
        })

    all_players.sort(key=lambda x: x["average"], reverse=True)
    players_to_display = [p for p in all_players if not position or p["position"].upper() == position.upper()]
    players_to_display = players_to_display[:150]

    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,  # Pass user to template
        "players": players_to_display,
        "year": year,
        "week": selected_week,
        "current_api_week": current_api_week,
        "selected_position": position or "",
        "selected_scoring": scoring,
        "all_players": all_players,
    })

# --- AI Routes ---

@app.get("/ai", response_class=HTMLResponse)
def ai_page(request: Request):
    user = get_current_user(request)
    year, week = stats.get_current_season_week()
    return templates.TemplateResponse("ai.html", {
        "request": request, 
        "user": user,
        "question": "", 
        "answer": "",
        "year": year,
        "week": week
    })

@app.get("/ask-agent", response_class=HTMLResponse)
def ask_agent_endpoint(
    request: Request, 
    q: str = Query(..., description="The user's question")
):
    user = get_current_user(request)
    
    roster_context = []
    if user:
        roster_context = user.get("team", [])

    print(f"Agent Query: '{q}' | User: {user['username'] if user else 'Guest'}")
    
    # UNPACK the tuple (Answer, Context)
    answer_text, context_used = ai_agent.ask_agent(q, roster_context)
    
    # LOGGING: Save to MongoDB for scoring later
    log_entry = {
        "user_id": user["_id"] if user else None,
        "username": user["username"] if user else "Guest",
        "question": q,
        "answer": answer_text,
        "context_used": context_used, # The raw stats the AI saw
        "timestamp": datetime.utcnow(),
        "metrics": {} # Placeholder for scores
    }
    ai_logs_collection.insert_one(log_entry)
    
    year, current_api_week = stats.get_current_season_week()

    return templates.TemplateResponse("ai.html", {
        "request": request,
        "user": user,
        "question": q,
        "answer": answer_text, # Pass just the text to the UI
        "year": year,
        "week": current_api_week,
        "current_api_week": current_api_week
    })

@app.get("/team", response_class=HTMLResponse)
async def team_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    user_team = user.get("team", [])
    
    # Get current week stats for the roster
    year, week = stats.get_current_season_week()
    enriched_team = []
    
    for player_obj in user_team:
        player_name = player_obj.get('name')
        if not player_name: continue
        
        # Try to find their stats for this week
        stat_entry = players_collection.find_one({
            "year": year, 
            "week": week, 
            "player": player_name
        })
        
        points = stat_entry.get("points", 0) if stat_entry else 0
        enriched_team.append({
            "name": player_name,
            "position": player_obj.get('position', 'N/A'),
            "team": player_obj.get('team', 'N/A'),
            "week_points": points
        })

    # NEW: Fetch all players for the autocomplete dropdown
    # We get players from the current week to ensure they are active
    available_players = list(players_collection.find(
        {"year": year, "week": week},
        {"_id": 0, "player": 1, "position": 1, "team": 1}
    ))

    return templates.TemplateResponse("team.html", {
        "request": request, 
        "user": user,
        "my_team": enriched_team, 
        "available_players": available_players, # Pass this new list to the template
        "year": year, 
        "week": week
    })

@app.get("/api/search-players")
def search_players(q: str = Query(..., min_length=2)):
    """
    Searches for players across the entire season (all weeks).
    Returns unique players (deduplicated by name) matching the query.
    """
    year, _ = stats.get_current_season_week()
    
    # Aggregation Pipeline:
    # 1. Match names resembling the query (case-insensitive)
    # 2. Group by player name (to remove duplicates from multiple weeks)
    # 3. Limit to 10 results for speed
    pipeline = [
        {"$match": {
            "player": {"$regex": q, "$options": "i"}, 
            "year": year
        }},
        {"$group": {
            "_id": "$player",
            "position": {"$first": "$position"},
            "team": {"$first": "$team"}
        }},
        {"$limit": 10}
    ]
    
    results = list(players_collection.aggregate(pipeline))
    
    # Format the output for the frontend
    return [
        {"name": r["_id"], "position": r["position"], "team": r["team"]} 
        for r in results
    ]

@app.get("/player/{player_name}", response_class=HTMLResponse)
def player_profile(request: Request, player_name: str):
    user = get_current_user(request)
    year, _ = stats.get_current_season_week()
    
    # FIX: Same strict filtering here
    weekly_stats = list(players_collection.find({
        "year": year,
        "player": player_name,
        "scoring_mode": "ppr",
        "points": {"$gt": 0} 
    }).sort("week", 1))
    
    if not weekly_stats:
        # Fallback if no games played yet
        return templates.TemplateResponse("player_detail.html", {
            "request": request, "user": user, "player_name": player_name,
            "stats": [], "average": 0, "total": 0, "position": "N/A", "team": "N/A"
        })

    total_points = sum(p['points'] for p in weekly_stats)
    games = len(weekly_stats)
    avg = total_points / games if games > 0 else 0

    return templates.TemplateResponse("player_detail.html", {
        "request": request,
        "user": user,
        "player_name": player_name,
        "stats": weekly_stats,
        "average": round(avg, 2),
        "total": round(total_points, 2),
        "position": weekly_stats[0].get('position', 'N/A'),
        "team": weekly_stats[0].get('team', 'N/A')
    })