import os
import re
from dotenv import load_dotenv
from pymongo import MongoClient

from google import genai
from google.genai import types

import stats  # for get_current_season_week


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
    Retrieves player stats from MongoDB with optional filters by player_name, week, and/or position.
    Returns a concise, human-readable list for the model to reason over.
    """
    print(f"Tool Used: get_player_stats_from_db(player={player_name}, week={week}, pos={position})")

    query = {"year": year, "scoring_mode": scoring}
    if player_name:
        query["player"] = {"$regex": re.escape(player_name), "$options": "i"}
    if week:
        query["week"] = week
    if position:
        query["position"] = {"$regex": f"^{position}$", "$options": "i"}

    # Default: show top scorers; if looking at a single player across time, show chronological
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


# Intent parser for historical leaderboard queries
POS_MAP = {
    r"\brb(s)?\b": "RB",
    r"\brunning backs?\b": "RB",
    r"\bwr(s)?\b": "WR",
    r"\bwide receivers?\b": "WR",
    r"\bqb(s)?\b": "QB",
    r"\bte(s)?\b": "TE",
    r"\bkickers?\b|\bk\b": "K",
    r"\bdef(ense)?\b": "DEF",
}

def _parse_historical_top_query(q: str):
    """
    Detects queries like 'top 5 RBs in week 4' and returns {week, position, limit}.
    Returns None if not a historical leaderboard query.
    """
    # Extract week number
    w = re.search(r"week\s+(\d+)", q, re.I)
    week = int(w.group(1)) if w else None
    
    # Extract limit (e.g., "top 5")
    t = re.search(r"top\s+(\d+)", q, re.I)
    limit = int(t.group(1)) if t else 5
    
    # Extract position
    position = None
    for pat, pos in POS_MAP.items():
        if re.search(pat, q, re.I):
            position = pos
            break
    
    if week and position:
        return {"week": week, "position": position, "limit": limit}
    return None


ai = genai.Client()  # Uses GEMINI_API_KEY/GOOGLE_API_KEY from env

# Turn 1: Search-only tool
search_tool = types.Tool(google_search=types.GoogleSearch())
config_search = types.GenerateContentConfig(
    tools=[search_tool],
    system_instruction=(
        "You are a fantasy football assistant. If the question is predictive or needs injuries/news/weather, "
        "use Google Search to gather current context, then produce a short preliminary outlook."
    ),
)

# Turn 2: DB function-only tool (no Search in this turn to avoid 400 error)
db_function_decl = types.FunctionDeclaration(
    name="get_player_stats_from_db",
    description="Retrieve fantasy player stats from MongoDB with optional filters.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "player_name": types.Schema(type="STRING", description="Player name substring match (case-insensitive)."),
            "week": types.Schema(type="INTEGER", description="NFL week number."),
            "position": types.Schema(type="STRING", description="One of QB, RB, WR, TE, K, DEF."),
            "limit": types.Schema(type="INTEGER", description="Max rows to return.", default=10),
            "scoring": types.Schema(
                type="STRING",
                description="Scoring mode: ppr, half_ppr, or standard.",
                enum=["ppr", "half_ppr", "standard"],
                default="ppr"
            ),
            "year": types.Schema(type="INTEGER", description="Season year.", default=2025),
        },
        required=[],
    ),
)
db_tool = types.Tool(function_declarations=[db_function_decl])
config_db = types.GenerateContentConfig(
    tools=[db_tool],
    system_instruction=(
        "You may call get_player_stats_from_db if weekly stats would improve the answer; "
        "otherwise continue with reasoning using the prior search summary. "
        "For historical 'top N at position in week W' queries, always call the DB tool."
    ),
)

# Turn 3: Final synthesis, no tools
config_final = types.GenerateContentConfig(
    tools=[],
    system_instruction=(
        "Synthesize a clear recommendation with concise evidence from search and stats; "
        "state uncertainty ranges if appropriate. Do NOT add preseason projections for historical queries."
    ),
)

MODEL = "gemini-2.5-flash"


def ask_agent(question: str) -> str:
    """
    Three-turn flow:
      0. If historical leaderboard query, short-circuit to DB directly.
      1. Search turn (for predictions/news).
      2. DB function call turn (if model decides).
      3. Final synthesis turn (no tools).
    """
    
    # Turn 0: DB-first short-circuit for historical leaderboard queries
    parsed = _parse_historical_top_query(question)
    if parsed:
        year, _ = stats.get_current_season_week()
        tool_result = get_player_stats_from_db(
            player_name=None,
            week=parsed["week"],
            position=parsed["position"],
            limit=parsed["limit"],
            scoring="ppr",
            year=year,
        )
        if tool_result.strip().startswith("No players"):
            return "No matching players were found for that week/position in the database."
        
        # Let the model format the output cleanly without adding projections
        final = ai.models.generate_content(
            model=MODEL,
            contents=(
                f"Database result for Week {parsed['week']} {parsed['position']} (top {parsed['limit']}, PPR):\n"
                f"{tool_result}\n\n"
                f"Rewrite as a clean numbered list titled 'Top {parsed['limit']} {parsed['position']}s – Week {parsed['week']}' "
                "including each player's team and points. Do NOT add projections, preseason context, or uncertainty disclaimers."
            ),
            config=config_final,
        )
        return clean_markdown_output(final.text or tool_result)
    

    # Turn 1: Search-only (for predictive/news queries)
    first = ai.models.generate_content(
        model=MODEL,
        contents=question,
        config=config_search,
    )
    
    # Build conversation history
    user_msg = types.Content(role="user", parts=[types.Part.from_text(text=question)])
    assistant_msg_1 = first.candidates[0].content if first.candidates else types.Content(role="model", parts=[])
    
    # Turn 2: DB function-only (no Search here to avoid 400 error)
    second = ai.models.generate_content(
        model=MODEL,
        contents=[user_msg, assistant_msg_1],
        config=config_db,
    )
    
    tool_calls = getattr(second, "function_calls", []) or []
    db_call = next((tc for tc in tool_calls if tc.name == "get_player_stats_from_db"), None)
    
    if db_call:
        args = dict(db_call.args) if hasattr(db_call, "args") else {}
        tool_result = get_player_stats_from_db(**args)
        
        func_resp_part = types.Part.from_function_response(
            name=db_call.name,
            response={"result": tool_result},
        )
        tool_content = types.Content(role="tool", parts=[func_resp_part])
        assistant_msg_2 = second.candidates[0].content if second.candidates else types.Content(role="model", parts=[])
        
        # Turn 3: Final synthesis (no tools)
        final = ai.models.generate_content(
            model=MODEL,
            contents=[user_msg, assistant_msg_1, assistant_msg_2, tool_content],
            config=config_final,
        )
        return clean_markdown_output(final.text or (first.text or ""))
    
    # If no DB call requested, finalize without tools
    final = ai.models.generate_content(
        model=MODEL,
        contents=[user_msg, assistant_msg_1],
        config=config_final,
    )
    return clean_markdown_output(final.text or (first.text or ""))

# Add this helper function to ai_agent.py

def clean_markdown_output(text: str) -> str:
    """
    Strips markdown formatting from Gemini output for cleaner, plain-text display.
    Converts:
      - **bold** → bold
      - *italic* → italic
      - Bullet points with * or - → plain text lines
    """
    if not text:
        return text
    
    # Remove bold (**text**)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    
    # Remove italic (*text* or _text_)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    
    # Convert bullet points to plain lines (preserve indentation with text, but remove the bullet)
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        # Strip leading bullet markers (* or -) and extra whitespace
        stripped = re.sub(r'^\s*[-*]\s+', '', line)
        if stripped:
            cleaned_lines.append(stripped)
        elif line.strip() == "":
            # Preserve blank lines for readability
            cleaned_lines.append("")
    
    # Join back and remove excessive blank lines
    result = '\n'.join(cleaned_lines)
    result = re.sub(r'\n\n+', '\n\n', result)  # Max 2 newlines
    
    return result.strip()
