# ai_agent.py
import os
from dotenv import load_dotenv
from pymongo import MongoClient
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# Load environment variables
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Database Connection ---
client = MongoClient(MONGO_URI)
db = client["fantasy_football"]
players_collection = db["players"]

# --- Tool Definition ---
# This is the Python function the AI will be able to call.

def get_player_stats_from_db(
    week: int,
    position: str = None,
    limit: int = 10,
    scoring: str = "ppr",
    year: int = 2025,
):
    """
    Retrieves player stats from the database for a specific week,
    with options to filter by position and limit the results.
    """
    print(f"Tool Used: get_player_stats_from_db(week={week}, position={position})")
    
    query = {"year": year, "week": week, "scoring_mode": scoring}
    if position:
        # Make position query case-insensitive
        query["position"] = {"$regex": f"^{position}$", "$options": "i"}

    # Find players, sort by points descending, and limit the results
    results = list(
        players_collection.find(query)
        .sort("points", -1)
        .limit(limit)
    )

    if not results:
        return "No players found matching those criteria."

    # Format the results into a clean string for the AI
    output_lines = []
    for player in results:
        name = player.get("player", "Unknown")
        pos = player.get("position", "N/A")
        team = player.get("team", "FA")
        points = player.get("points", 0)
        output_lines.append(f"- {name} ({pos}, {team}): {points:.2f} points")
    
    return "\n".join(output_lines)

# --- Configure Gemini with the Tool ---
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    "gemini-2.5-flash",  # Tool use works best with more advanced models
    tools=[get_player_stats_from_db],
    
    safety_settings={
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    }
)

def ask_agent(question: str):
    """
    This function orchestrates the conversation with the AI agent.
    """
    try:
        # 1. Send the user's question to the model
        response = model.generate_content(question)
        
        # 2. Check if the model wants to use our tool
        if response.candidates[0].content.parts[0].function_call:
            function_call = response.candidates[0].content.parts[0].function_call
            
            # 3. Extract the function name and arguments the AI wants to use
            tool_name = function_call.name
            tool_args = dict(function_call.args)

            # 4. Call our actual Python function with the arguments
            if tool_name == "get_player_stats_from_db":
                tool_result = get_player_stats_from_db(**tool_args)

                # 5. Send the result from our tool back to the AI
                final_response = model.generate_content(
                    f"Tool Response: {tool_result}\n\nBased on this data, answer the original question: {question}"
                )
                return final_response.text.strip()

        # If the model didn't need a tool (e.g., "hello"), just return its response
        return response.text.strip()
        
    except Exception as e:
        print(f"--- DETAILED AGENT ERROR --- \n{e}\n ---------------------------")
        return f"Sorry, there was an error with the AI agent: {e}"