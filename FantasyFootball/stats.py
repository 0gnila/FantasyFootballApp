# stats.py
import requests
import time
from datetime import datetime

# We no longer need pointFunctions here, simplifying the code.

players_url = "https://api.sleeper.app/v1/players/nfl"
try:
    players = requests.get(players_url, timeout=10).json()
except Exception:
    players = {}

def get_week_stats(year: int, week: int, scoring_mode="ppr"):
    """
    Fetches stats and USES THE PRE-CALCULATED FANTASY POINTS from the Sleeper API.
    This is the correct and most accurate method.
    """
    url = f"https://api.sleeper.app/v1/stats/nfl/regular/{year}/{week}"
    response = requests.get(url).json()
    
    fantasy_stats = []
    
    ALLOWED_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}

    for player_id, stats_dict in response.items():
        player_info = players.get(player_id, {})
        pos = player_info.get('position', 'Unknown')

        if pos not in ALLOWED_POSITIONS:
            continue

        # --- THE FIX IS HERE ---
        # Instead of recalculating, we get the points directly from the API.
        
        # Determine the correct key for the scoring mode.
        # Sleeper uses 'pts_std', 'pts_ppr', 'pts_half_ppr'
        points_key = f"pts_{scoring_mode}"
        if scoring_mode == "standard":
            points_key = "pts_std"
        
        # Get the pre-calculated points. Default to 0.0 if the key doesn't exist.
        points = stats_dict.get(points_key, 0.0)
        
        # Ensure points is a float, as it can be None from the API
        if points is None:
            points = 0.0
        # ---------------------

        # Get player name and clean it up
        name = player_info.get('full_name') or f"{player_info.get('first_name', '')} {player_info.get('last_name', '')}".strip()
        if not name: name = "Unknown Player"
        
        if pos == "DEF" and name == "Unknown Player":
            name = f"{player_info.get('team', 'N/A')} Defense"
        
        team = player_info.get('team', 'FA')

        fantasy_stats.append({
            "player": name,
            "position": pos,
            "team": team,
            "points": points, # Use the accurate, direct value
            "stats": stats_dict
        })

    return {"week": week, "year": year, "fantasy_stats": fantasy_stats}


# --- This function remains the same ---
_last_week_cache = {"data": None, "timestamp": 0}

def get_current_season_week():
    if time.time() - _last_week_cache["timestamp"] < 600 and _last_week_cache["data"]:
        return _last_week_cache["data"]

    url = "https://api.sleeper.app/v1/state/nfl"
    default_year = datetime.now().year
    
    try:
        response = requests.get(url, timeout=10).json()
        
        year = int(response.get("season", default_year))
        week = int(response.get("week", 1))
            
        if week < 1: week = 1
        
        print(f"📅 Sleeper API reports: {year} Week {week}")

        test_url = f"https://api.sleeper.app/v1/stats/nfl/regular/{year}/{week}"
        test_data = requests.get(test_url, timeout=10).json()

        if not test_data and week > 1:
            print(f"⚠️ No stats found for Week {week}, falling back to Week {week-1}")
            week = week - 1

        data = (year, week)
        _last_week_cache["data"] = data
        print(f"✅ Returning (Year: {year}, Week: {week})")
        return data

    except Exception as e:
        print(f"❌ Error fetching current week: {e}. Defaulting to ({default_year}, 1).")
        return (default_year, 1)