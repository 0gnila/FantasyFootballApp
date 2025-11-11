# rag.py
import os
from dotenv import load_dotenv
from pymongo import MongoClient
import google.generativeai as genai
import stats

# Load environment variables
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash") 

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client["fantasy_football"]
players_collection = db["players"]


def get_context_from_mongo(year, week, scoring="ppr"):
    """
    Retrieve data for a specific week from MongoDB.
    """
    print(f" Building context for Year {year}, Week {week} ({scoring})")

    docs = list(players_collection.find({
        "year": year, 
        "week": week,
        "scoring_mode": scoring
    }))

    if not docs:
        print(" No fantasy data found for context!")
        return ""

    # Create a readable text summary for Gemini
    context_lines = []
    # Sort by points, descending, to give Gemini the most relevant players first
    docs.sort(key=lambda x: x.get("points", 0), reverse=True)
    
    for p in docs[:100]: # Limit context to top 100 players
        name = p.get("player", "Unknown")
        pos = p.get("position", "N/A")
        team = p.get("team", "FA")
        points = p.get("points", 0)
        context_lines.append(f"{name} ({pos}, {team}) scored {points:.2f} {scoring} points.")

    context_text = "\n".join(context_lines)
    print(f"Prepared context with {len(docs)} player stats.")
    return context_text


def ask_gemini(question: str, year: int, week: int, scoring: str):
    """
    Ask Gemini a fantasy football question with context retrieved from MongoDB.
    """
    context = get_context_from_mongo(year, week, scoring)

    if not context.strip():
        return "Sorry, I couldn’t find any player data to answer that. The database might be empty."

    prompt = f"""
You are a Fantasy Football assistant.
You have access to the following player data from Year {year}, Week {week} ({scoring} scoring):
{context}

Now answer this question based *only* on the data provided above:
Question: {question}

If possible, include the player's name, team, and points in your answer.
    """

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"--- DETAILED GEMINI ERROR --- \n{e}\n ---------------------------")
        return f"Error: {e}"