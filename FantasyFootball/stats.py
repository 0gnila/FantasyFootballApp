from collections import defaultdict
import requests
import pointFunctions

calculate_points = pointFunctions.calculate_points

players_url = "https://api.sleeper.app/v1/players/nfl"
try:
    players = requests.get(players_url, timeout=10).json()
except Exception:
    players = {}


def compute_player_season_average(player_name, year, scoring_mode, players_collection):
    """
    Average points for the season, ignoring weeks not played.
    """
    player_weeks = list(players_collection.find({
        "player": player_name,
        "year": year,
        "scoring_mode": scoring_mode
    }))
    if not player_weeks:
        return 0.0

    total_points = sum(p.get("points", 0) for p in player_weeks)
    played_weeks = len(player_weeks)
    return round(total_points / played_weeks, 2)
    
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
    import time, requests

    # Use cached data if it's fresh (less than 10 minutes old)
    if time.time() - _last_week_cache["timestamp"] < 600 and _last_week_cache["data"]:
        return _last_week_cache["data"]

    url = "https://api.sleeper.app/v1/state/nfl"
    try:
        response = requests.get(url, timeout=10).json()
        year = response.get("season")
        week = response.get("week")

        # 🏈 Safety check: if no valid week (offseason or future week), go back one
        if not week or week < 1:
            print("⚠️ Sleeper returned invalid week — defaulting to Week 1.")
            week = 1
        else:
            print(f"📅 Sleeper reports: {year} Week {week}")

        # Try fetching data for this week
        test_url = f"https://api.sleeper.app/v1/stats/nfl/regular/{year}/{week}"
        test_data = requests.get(test_url, timeout=10).json()

        # If no players found, fallback to previous week
        if not test_data:
            print(f"⚠️ No stats found for Week {week}, falling back to Week {week-1}")
            week = max(1, week - 1)

        data = (year, week)
        _last_week_cache["data"] = data
        _last_week_cache["timestamp"] = time.time()
        return data

    except Exception as e:
        print("❌ Error fetching current week:", e)
        # Return cached data if available, otherwise default safe value
        return _last_week_cache["data"] or (2024, 18)
    