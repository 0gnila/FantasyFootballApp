import os
import json
import time
from dotenv import load_dotenv
from pymongo import MongoClient
import google.generativeai as genai

# 1. Setup & Configuration
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Connect to DB
client = MongoClient(MONGO_URI)
db = client["fantasy_football"]
ai_logs = db["ai_logs"]

# Configure the "Judge" Model
genai.configure(api_key=GEMINI_API_KEY)
judge_model = genai.GenerativeModel("gemini-2.5-flash")

def evaluate_logs():
    print("--- Starting G-Eval (AI Judge) ---")
    
    # 2. Find ALL unscored logs (removed the context filter)
    logs_to_score = list(ai_logs.find({
        "metrics.geval_score": {"$exists": False}
    }))
    
    if not logs_to_score:
        print("No new logs to evaluate. (Try asking a new question on the site first!)")
        return

    print(f"Found {len(logs_to_score)} interactions to grade...")

    for log in logs_to_score:
        try:
            question = log.get('question', '')
            answer = log.get('answer', '')
            context = log.get('context_used', '')

            # 3. Dynamic Prompting based on Context
            if context:
                # SCENARIO A: RAG (Data was used) -> Check Accuracy
                prompt = f"""
                You are a strict Fantasy Football Judge. Grade this interaction 1-5.

                ### INPUT
                1. User Question: "{question}"
                2. Database Stats (Fact Source): "{context}"
                3. AI Answer: "{answer}"

                ### RUBRIC (Data Available)
                - 1: Hallucination (states numbers not in source) or wrong player.
                - 3: Correct stats but vague advice.
                - 5: Perfectly accurate stats and specific, helpful advice.

                Return strictly JSON: {{"score": <int>, "reasoning": "<string>"}}
                """
            else:
                # SCENARIO B: Conversational (No Data) -> Check Helpfulness
                prompt = f"""
                You are a helpful Fantasy Football Judge. Grade this interaction 1-5.
                
                ### INPUT
                1. User Question: "{question}"
                2. AI Answer: "{answer}"
                (Note: No database stats were retrieved for this query.)

                ### RUBRIC (No Data)
                - 1: Completely irrelevant or refused to answer.
                - 3: Generic advice, helpful but basic.
                - 5: Highly specific, relevant, and actionable advice.

                Return strictly JSON: {{"score": <int>, "reasoning": "<string>"}}
                """

            # 4. Call the Judge
            response = judge_model.generate_content(prompt)
            
            # Clean JSON
            cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
            result = json.loads(cleaned_text)
            
            score = result.get("score")
            reasoning = result.get("reasoning")

            # 5. Update MongoDB
            ai_logs.update_one(
                {"_id": log["_id"]},
                {"$set": {
                    "metrics.geval_score": score,
                    "metrics.geval_reasoning": reasoning,
                    "metrics.evaluated_at": time.time()
                }}
            )
            
            print(f" -> Scored Log: {score}/5 | Reason: {reasoning}")
            time.sleep(1) # Rate limit safety

        except Exception as e:
            print(f"Error grading log {log.get('_id')}: {e}")

    print("--- Evaluation Complete ---")

if __name__ == "__main__":
    evaluate_logs()