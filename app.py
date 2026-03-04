#-*- coding: utf-8 -*-
"""
Autoanosis AI Backend v5.15.0 (STABILIZATION)
- SECURITY: System prompt updated to enforce medical-safe AI behavior.
- FEATURE: AI is now instructed to be transparent about the quantity and source of data.
- FEATURE: AI will now explicitly state when data is NOT found.
- CHORE: General code cleanup and comment improvements.
"""

import os
import time
import logging
import uuid
from collections import defaultdict

from flask import Flask, request, jsonify
from openai import OpenAI

from identity import verify_identity_token
from ocr_endpoint import ocr_bp

# --- Basic Setup ---
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Register Blueprints ---
app.register_blueprint(ocr_bp)

# --- System Prompts --- 

# This is the new, safer system prompt.
SYSTEM_PROMPT_STABLE = """You are Autoanosis Assistant, a specialized health assistant in Greek.

CORE DIRECTIVES:
1.  **Medical Safety First**: NEVER provide a diagnosis. NEVER guess or hallucinate information. If data is not in the user's profile, you MUST state that it is not available.
2.  **Source Clarity**: ALWAYS cite the source of your information. Start answers about user data with "According to your Autoanosis profile..." or "From your lab results dated..."
3.  **Data Transparency**: ALWAYS quantify the data you see. State HOW MANY records you are referencing. Examples: "I see 2 lab reports...", "I see 5 entries in your symptom diary...", "There are 3 active medications listed."
4.  **Use Provided Context ONLY**: Your knowledge of the user is strictly limited to the medical profile provided below. Do not refer to past conversations. If no profile is provided, you MUST state that you have no access to personal data.

RESPONSE FORMATTING:
- All responses must be in Greek.
- Use Markdown for clear formatting (lists, bolding).
- When mentioning medications, ALWAYS include the time slots if available (e.g., "TRANXENE 20mg (at 23:10)").

B.E.S.T. PROTOCOL DEFINITION:
- The B.E.S.T. protocol is a structured format for preparing for a doctor's appointment (Baseline, Events, Symptoms, Targets). It is NOT a blood test.

USER MEDICAL PROFILE:
{snapshot}
"""

# Base prompt for when no context is available
SYSTEM_PROMPT_BASE = """You are Autoanosis Assistant, a specialized health assistant in Greek.

Your primary function is to provide general health information. You must adhere to the following rules:
1.  You do not have access to any personal user data, medical records, or conversation history.
2.  You MUST politely decline any questions that require personal data (e.g., "What are my medications?", "Do you remember my diagnosis?"). A safe response is: "As an AI assistant, I do not have access to your personal health records."
3.  All responses must be in Greek.
"""

# --- OpenAI Client --- 
def get_openai_client():
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# --- Rate Limiting --- 
rate_limit_storage = defaultdict(list)
RATE_LIMIT_USER = 30
RATE_LIMIT_WINDOW = 600  # 10 minutes

def check_rate_limit(identifier: str) -> bool:
    now = time.time()
    rate_limit_storage[identifier] = [
        t for t in rate_limit_storage[identifier] if now - t < RATE_LIMIT_WINDOW
    ]
    if len(rate_limit_storage[identifier]) >= RATE_LIMIT_USER:
        return False
    rate_limit_storage[identifier].append(now)
    return True

# --- Context Extraction --- 

def build_medical_context_from_helpers_snapshot(snap: dict) -> str:
    """Builds a detailed, human-readable context string from the PHP snapshot."""
    if not snap or not isinstance(snap, dict):
        return ""
    parts = []

    # User Info
    if snap.get("user_name"): parts.append(f"- Name: {snap['user_name']}")
    if snap.get("autoimmune_type"): parts.append(f"- Condition: {snap['autoimmune_type']}")
    if snap.get("health_info"): parts.append(f"- General Health Info: {snap['health_info'].strip()}")

    # Medications (Active + Inactive History)
    meds = snap.get("medications")
    if isinstance(meds, list) and meds:
        active_meds = [m for m in meds if m.get("status") == "active"]
        inactive_meds = [m for m in meds if m.get("status") != "active"]
        lines = [f"Found {len(meds)} total medication records ({len(active_meds)} active)."]
        if active_meds:
            lines.append("  Active Medications:")
            for m in active_meds:
                line = f"    - {m.get('medication_name', 'N/A')} {m.get('dosage', '')}"
                slots = m.get('time_slots')
                if slots and isinstance(slots, list): line += f" (at: {', '.join(slots)})"
                lines.append(line)
        if inactive_meds:
            lines.append("  Past Medications:")
            for m in inactive_meds:
                lines.append(f"    - {m.get('medication_name', 'N/A')} (inactive since {m.get('created_at', 'N/A')})")
        parts.append("\n".join(lines))

    # Lab Results (Full History)
    test_results = snap.get("test_results")
    if isinstance(test_results, list) and test_results:
        lines = [f"Found {len(test_results)} lab reports."]
        for r in test_results:
            lines.append(f"  - {r.get('test_date', 'N/A')}: {r.get('test_name', 'N/A')} - {r.get('result_value', 'N/A')} {r.get('unit', '')}")
        parts.append("\n".join(lines))

    # Symptoms Diary (Last 30 days)
    symptoms = snap.get("recent_symptoms")
    if isinstance(symptoms, list) and symptoms:
        lines = [f"Found {len(symptoms)} symptom entries from the last 30 days."]
        for s in symptoms:
            lines.append(f"  - {s.get('recorded_at', 'N/A')}: {s.get('symptom_name', 'N/A')}")
        parts.append("\n".join(lines))

    # BEST Protocol (Last 5 entries)
    best_history = snap.get("best_history")
    if isinstance(best_history, list) and best_history:
        lines = [f"Found {len(best_history)} B.E.S.T. protocol entries."]
        for i, b in enumerate(best_history, 1):
            lines.append(f"  {i}. Entry from {b.get('visit_date', 'N/A')} for Dr. {b.get('visit_doctor', 'N/A')}")
        parts.append("\n".join(lines))

    if not parts:
        return "No medical data found in profile."
    
    return "\n".join(parts)

# --- Main Chat Endpoint --- 
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400

    user_message = data.get("message")
    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    # --- Authenticate user ---
    user_id = None
    identity_token = data.get("identity_token")
    if identity_token:
        is_valid, payload, error = verify_identity_token(identity_token)
        if is_valid and payload:
            user_id = payload.get("uid")
            logger.info(f"[AUTH] User authenticated: {user_id}")
        else:
            logger.warning(f"[AUTH] Identity token failed: {error}")
            return jsonify({"error": "Invalid identity token"}), 401
    else:
        return jsonify({"error": "Identity token required"}), 401

    # --- Rate limit ---
    if not check_rate_limit(f"user_{user_id}"):
        return jsonify({"error": "Rate limit exceeded."}), 429

    # --- Medical Context --- 
    medical_snapshot = data.get("medical_snapshot")
    snapshot_str = ""
    if isinstance(medical_snapshot, dict):
        snapshot_str = build_medical_context_from_helpers_snapshot(medical_snapshot)
        logger.info(f"[CONTEXT] Built medical context for user={user_id}")
    else:
        logger.warning(f"[CONTEXT] No medical snapshot provided for user={user_id}")

    # --- Build System Prompt ---
    if snapshot_str:
        system_prompt = SYSTEM_PROMPT_STABLE.format(snapshot=snapshot_str)
    else:
        system_prompt = SYSTEM_PROMPT_BASE

    # --- Call OpenAI --- 
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.5 # Lower temperature for more factual responses
        )
        ai_response = response.choices[0].message.content
        logger.info(f"[CHAT] successful response for user={user_id}")
        return jsonify({"reply": ai_response})

    except Exception as e:
        logger.error(f"[OPENAI] Error for user={user_id}: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
