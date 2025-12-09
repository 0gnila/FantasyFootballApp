import os
import re
from dotenv import load_dotenv
from pymongo import MongoClient

from google import genai
from google.genai import types

import stats

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

client_db = MongoClient(MONGO_URI)
db = client_db["fantasy_football"]
players_collection = db["players"]


def get_player_stats_from_db(
    player_name: str = None,
    week: int = None,
    position: str = None,
    limit: int = 10,
    scoring: str = "ppr",
    year: int = 2025,
) -> str:
    """
    Retrieves player stats from MongoDB.
    """
    print(f"Tool Used: get_player_stats_from_db(player={player_name}, week={week}, pos={position})")

    query = {"year": year, "scoring_mode": scoring}
    if player_name:
        query["player"] = {"$regex": re.escape(player_name), "$options": "i"}
    if week:
        query["week"] = week
    if position:
        query["position"] = {"$regex": f"^{position}$", "$options": "i"}

    sort_key, sort_order = ("points", -1)
    if player_name and not week:
        sort_key, sort_order = ("week", 1)

    results = list(
        players_collection.find(query)
        .sort(sort_key, sort_order)
        .limit(limit)
    )

    if not results:
        return "No players found matching those criteria."

    lines = []
    for p in results:
        name = p.get("player", "Unknown")
        pos = p.get("position", "N/A")
        team = p.get("team", "FA")
        pts = p.get("points", 0)
        wk = p.get("week", 0)
        lines.append(f"- Week {wk}: {name} ({pos}, {team}): {pts:.2f} points")
    return "\n".join(lines)


# --- Intent Parsing & Tool Definitions ---
POS_MAP = {
    r"\brb(s)?\b": "RB", r"\brunning backs?\b": "RB",
    r"\bwr(s)?\b": "WR", r"\bwide receivers?\b": "WR",
    r"\bqb(s)?\b": "QB", r"\bte(s)?\b": "TE",
    r"\bkickers?\b|\bk\b": "K", r"\bdef(ense)?\b": "DEF",
}

def _parse_historical_top_query(q: str):
    w = re.search(r"week\s+(\d+)", q, re.I)
    week = int(w.group(1)) if w else None
    t = re.search(r"top\s+(\d+)", q, re.I)
    limit = int(t.group(1)) if t else 5
    position = None
    for pat, pos in POS_MAP.items():
        if re.search(pat, q, re.I):
            position = pos
            break
    if week and position:
        return {"week": week, "position": position, "limit": limit}
    return None

ai = genai.Client()

search_tool = types.Tool(google_search=types.GoogleSearch())
config_search = types.GenerateContentConfig(
    tools=[search_tool],
    system_instruction="You are a fantasy football assistant. Check news/projections via search."
)

db_function_decl = types.FunctionDeclaration(
    name="get_player_stats_from_db",
    description="Retrieve fantasy player stats from MongoDB.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "player_name": types.Schema(type="STRING"),
            "week": types.Schema(type="INTEGER"),
            "position": types.Schema(type="STRING"),
            "limit": types.Schema(type="INTEGER", default=10),
            "scoring": types.Schema(type="STRING", enum=["ppr", "half_ppr", "standard"], default="ppr"),
            "year": types.Schema(type="INTEGER", default=2025),
        },
        required=[],
    ),
)
db_tool = types.Tool(function_declarations=[db_function_decl])
config_db = types.GenerateContentConfig(
    tools=[db_tool],
    system_instruction="Use get_player_stats_from_db to see past performance. Combine with your knowledge."
)

config_final = types.GenerateContentConfig(
    tools=[],
    system_instruction="Synthesize a recommendation. If the user asked 'Who should I start?', choose specific players from their roster if provided."
)

MODEL = "gemini-2.5-flash"

def _extract_text(candidate):
    """
    Safely extracts text parts from a generation candidate, ignoring function calls.
    """
    if not candidate or not candidate.content or not candidate.content.parts:
        return ""
    
    text_parts = []
    for part in candidate.content.parts:
        if part.text:
            text_parts.append(part.text)
    return "\n".join(text_parts)

# 2. UPDATE THE MAIN AGENT FUNCTION
def ask_agent(question: str, user_roster: list = None) -> tuple[str, str]:
    """
    Handles the question, returning (Answer Text, Context String).
    """
    
    # 1. Prepend Roster Context
    if user_roster:
        roster_str = ", ".join([f"{p['name']} ({p['position']})" for p in user_roster])
        context_prompt = (
            f"CONTEXT - MY ROSTER: [{roster_str}]\n"
            f"If I ask 'who to start', pick from these players.\n\n"
            f"USER QUESTION: {question}"
        )
    else:
        context_prompt = question

    # Turn 0: Historical Short Circuit (Keep as is)
    parsed = _parse_historical_top_query(question)
    if parsed:
        year, _ = stats.get_current_season_week()
        tool_result = get_player_stats_from_db(
            week=parsed["week"], position=parsed["position"], limit=parsed["limit"], year=year
        )
        final = ai.models.generate_content(
            model=MODEL,
            contents=f"Convert this DB data to a clean list: {tool_result}",
            config=config_final,
        )
        return clean_markdown_output(final.text), tool_result

    # Turn 1: Search (The AI might answer here!)
    first = ai.models.generate_content(
        model=MODEL,
        contents=context_prompt,
        config=config_search,
    )
    
    # Save the text from Turn 1 (This is what you were missing)
    first_text = _extract_text(first.candidates[0] if first.candidates else None)
    
    user_msg = types.Content(role="user", parts=[types.Part.from_text(text=context_prompt)])
    assistant_msg_1 = first.candidates[0].content if first.candidates else types.Content(role="model", parts=[])
    
    # Turn 2: DB Tool Check
    second = ai.models.generate_content(
        model=MODEL,
        contents=[user_msg, assistant_msg_1],
        config=config_db,
    )
    
    # Save the text from Turn 2
    second_text = _extract_text(second.candidates[0] if second.candidates else None)
    assistant_msg_2 = second.candidates[0].content if second.candidates else types.Content(role="model", parts=[])
    
    tool_calls = getattr(second, "function_calls", []) or []
    db_call = next((tc for tc in tool_calls if tc.name == "get_player_stats_from_db"), None)
    
    # CASE A: DB Tool Was Called
    if db_call:
        args = dict(db_call.args) if hasattr(db_call, "args") else {}
        tool_result = get_player_stats_from_db(**args)
        
        func_resp_part = types.Part.from_function_response(
            name=db_call.name, response={"result": tool_result}
        )
        tool_content = types.Content(role="tool", parts=[func_resp_part])
        
        final = ai.models.generate_content(
            model=MODEL,
            contents=[user_msg, assistant_msg_1, assistant_msg_2, tool_content],
            config=config_final,
        )
        return clean_markdown_output(final.text), tool_result
    
    # CASE B: No DB Tool (The Fix)
    # We combine the text from Turn 1 and Turn 2.
    # Usually Turn 1 has the answer, and Turn 2 is just empty or a closing remark.
    full_answer = f"{first_text}\n\n{second_text}".strip()
    
    return clean_markdown_output(full_answer), ""

def clean_markdown_output(text: str) -> str:
    if not text: return ""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text) 
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    return text