from collections import defaultdict
import requests
import pointFunctions

calculate_points = pointFunctions.calculate_points

players_url = "https://api.sleeper.app/v1/players/nfl"
try:
    players = requests.get(players_url, timeout=10).json()
except Exception:
    players = {}


def get_week_stats(year: int, week: int, scoring_mode="ppr"):
    url = f"https://api.sleeper.app/v1/stats/nfl/regular/{year}/{week}"
    response = requests.get(url).json()
    
    fantasy_stats = []
    team_defenses = defaultdict(lambda: defaultdict(int))
    
    for player_id, stats_dict in response.items():
        player_info = players.get(player_id, {})
        pos = player_info.get('position', 'Unknown')
        team = player_info.get('team', 'FA')

        if pos in {"CB", "S", "LB", "DL", "DE", "DT"} and team != "FA":
            for k, v in stats_dict.items():
                team_defenses[team][k] += v
            continue

        name = player_info.get('full_name', 'Unknown')
        points = calculate_points(stats_dict, pos, scoring_mode=scoring_mode)

        fantasy_stats.append({
            "player": name,
            "position": pos,
            "team": team,
            "points": points,
            "stats": stats_dict
        })

    # Process team defenses
    for team, def_stats in team_defenses.items():
        points = calculate_points(def_stats, "DEF", scoring_mode=scoring_mode)
        fantasy_stats.append({
            "player": f"{team} Defense",
            "position": "DEF",
            "team": team,
            "points": points,
            "stats": def_stats
        })

    return {"week": week, "year": year, "fantasy_stats": fantasy_stats}

import time

_last_week_cache = {"data": None, "timestamp": 0}

def get_current_season_week():
    # Use cached data if it's fresh (less than 10 minutes old)
    if time.time() - _last_week_cache["timestamp"] < 600 and _last_week_cache["data"]:
        return _last_week_cache["data"]

    url = "https://api.sleeper.app/v1/state/nfl"
    try:
        response = requests.get(url, timeout=10).json()
        data = (response["season"], response["week"])
        _last_week_cache["data"] = data
        _last_week_cache["timestamp"] = time.time()
        return data
    except Exception as e:
        print("Error fetching current week:", e)
        # Return cached data if available, otherwise a default value
        return _last_week_cache["data"] or (None, None)

def get_sleeper_projections(year, week):
    url = f"https://api.sleeper.app/v1/projections/nfl/regular/{year}/{week}"
    try:
        response = requests.get(url, timeout=10)
        return response.json()
    except Exception:
        return {}

def average_projections(sleeper_proj):
    return round(sleeper_proj or 0, 2)

def get_player_metadata():
    url = "https://api.sleeper.com/players/nfl"
    try:
        response = requests.get(url, timeout=10).json()
        return response
    except Exception:
        return {}