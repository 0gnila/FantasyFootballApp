# populate_db.py
import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timezone
import stats

# Load environment variables
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    print("Error: MONGO_URI not found in .env file.")
    sys.exit(1)

# Connect to MongoDB
try:
    client = MongoClient(MONGO_URI)
    db = client["fantasy_football"]
    players_collection = db["players"]
    client.admin.command('ping')
    print("MongoDB connection successful.")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")
    sys.exit(1)


def backfill_all_data():
    """
    Fetches and saves stats for all weeks and all scoring modes.
    This will DELETE old data for a week before inserting new data.
    """
    current_year, current_week = stats.get_current_season_week()
    scoring_modes = ["ppr", "half_ppr", "standard"]
    
    print(f"Starting backfill for {current_year}, Weeks 1-{current_week}...")

    for week in range(1, current_week + 1):
        for scoring in scoring_modes:
            print(f"Processing Year {current_year}, Week {week} ({scoring})...")
            
            # Delete any old/bad data for this week first
            delete_query = {
                "year": current_year, 
                "week": week, 
                "scoring_mode": scoring
            }
            result = players_collection.delete_many(delete_query)
            if result.deleted_count > 0:
                print(f"  -> Cleared {result.deleted_count} old entries.")

            # Fetch from Sleeper API
            week_stats = stats.get_week_stats(current_year, week, scoring_mode=scoring)
            week_stats_list = week_stats.get("fantasy_stats", [])
            
            if not week_stats_list:
                print(f"  -> No data found for Week {week}.")
                continue

            # Add metadata for querying
            for p in week_stats_list:
                p.update({
                    "year": current_year,
                    "week": week,
                    "scoring_mode": scoring,
                    # --- THIS IS THE FIX ---
                    "last_updated": datetime.now(timezone.utc)
                })
            
            # Insert new, correct data
            players_collection.insert_many(week_stats_list)
            print(f"  -> Cached {len(week_stats_list)} new players for Week {week} ({scoring}).")

    print("\n Database backfill complete.")


if __name__ == "__main__":
    backfill_all_data()