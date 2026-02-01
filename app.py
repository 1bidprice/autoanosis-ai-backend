"""
Autoanosis AI Backend v3
Professional Flask backend for AI Assistant with Medical Context
Deployed on Render.com
"""

import os
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from identity import verify_identity_token

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Configure CORS - allow requests from autoanosis.com
CORS(app, resources={
    r"/*": {
        "origins": [
            "https://autoanosis.com",
            "https://www.autoanosis.com"
        ],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-User-ID"],
        "supports_credentials": True
    }
})

# Configure OpenAI client (lazy initialization)
openai_client = None

def get_openai_client():
    global openai_client
    if openai_client is None:
        openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return openai_client

# Token Bridge Configuration
TOKEN_SECRET = os.environ.get("AUTOANOSIS_IDENTITY_SECRET", "CHANGE_THIS_SECRET")

# Rate limiting storage (in-memory)
rate_limit_storage = defaultdict(list)
RATE_LIMIT_USER = 20  # 20 requests per 10 minutes for authenticated users
RATE_LIMIT_WINDOW = 600  # 10 minutes in seconds

# Session Memory Storage (in-memory)
# Format: {conversation_id: {"messages": [...], "last_activity": timestamp, "user_id": int}}
conversation_storage = {}
MAX_CONVERSATION_HISTORY = 10  # Keep last 10 messages per conversation
CONVERSATION_TTL = 3600  # 1 hour

# System prompt for Autoanosis health assistant
SYSTEM_PROMPT_BASE = """Είσαι ο Autoanosis Assistant, ένας εξειδικευμένος βοηθός υγείας στα ελληνικά.

Παρέχεις:
- Ακριβείς και επιστημονικά τεκμηριωμένες πληροφορίες υγείας
- Φιλικές και κατανοητές απαντήσεις
- Υποστήριξη σε θέματα υγείας, φαρμάκων, συμπτωμάτων

Σημαντικό:
- ΔΕΝ αντικαθιστάς ιατρική συμβουλή
- Συνιστάς πάντα επίσκεψη σε γιατρό για σοβαρά θέματα
- Απαντάς στα ελληνικά"""

def check_rate_limit(identifier: str) -> bool:
    """Check if identifier has exceeded rate limit"""
    current_time = time.time()
    
    # Clean old entries
    rate_limit_storage[identifier] = [
        t for t in rate_limit_storage[identifier] 
        if current_time - t < RATE_LIMIT_WINDOW
    ]
    
    # Check limit
    if len(rate_limit_storage[identifier]) >= RATE_LIMIT_USER:
        return False
    
    # Record this request
    rate_limit_storage[identifier].append(current_time)
    return True

def cleanup_old_conversations():
    """Remove expired conversations"""
    current_time = time.time()
    expired = [
        conv_id for conv_id, data in conversation_storage.items()
        if current_time - data.get('last_activity', 0) > CONVERSATION_TTL
    ]
    for conv_id in expired:
        del conversation_storage[conv_id]
        logger.info(f"Cleaned up expired conversation: {conv_id}")

def get_conversation_history(conversation_id: str) -> list:
    """Get conversation history for context"""
    if conversation_id not in conversation_storage:
        return []
    return conversation_storage[conversation_id].get('messages', [])

def save_conversation_message(conversation_id: str, user_id: int, role: str, content: str):
    """Save message to conversation history"""
    if conversation_id not in conversation_storage:
        conversation_storage[conversation_id] = {
            'messages': [],
            'user_id': user_id,
            'last_activity': time.time()
        }
    
    conv = conversation_storage[conversation_id]
    conv['messages'].append({'role': role, 'content': content})
    conv['last_activity'] = time.time()
    
    # Keep only last N messages
    if len(conv['messages']) > MAX_CONVERSATION_HISTORY:
        conv['messages'] = conv['messages'][-MAX_CONVERSATION_HISTORY:]

def build_medical_context(medical_snapshot: dict) -> str:
    """Build medical context string from snapshot"""
    if not medical_snapshot or not isinstance(medical_snapshot, dict):
        return ""
    
    context_parts = []
    
    # Medications
    meds = medical_snapshot.get('autoanosis_medications')
    if meds and isinstance(meds, list) and len(meds) > 0:
        med_names = [m.get('name', '') for m in meds if isinstance(m, dict) and m.get('name')]
        if med_names:
            context_parts.append(f"Φάρμακα που παίρνει: {', '.join(med_names)}")
    
    # Conditions
    conditions = medical_snapshot.get('autoanosis_conditions')
    if conditions and isinstance(conditions, list) and len(conditions) > 0:
        cond_names = [c.get('name', '') for c in conditions if isinstance(c, dict) and c.get('name')]
        if cond_names:
            context_parts.append(f"Παθήσεις: {', '.join(cond_names)}")
    
    # Allergies
    allergies = medical_snapshot.get('autoanosis_allergies')
    if allergies and isinstance(allergies, list) and len(allergies) > 0:
        allergy_names = [a.get('name', '') for a in allergies if isinstance(a, dict) and a.get('name')]
        if allergy_names:
            context_parts.append(f"Αλλεργίες: {', '.join(allergy_names)}")
    
    # Medical Memory (recent notes)
    memory = medical_snapshot.get('autoanosis_medical_memory')
    if memory and isinstance(memory, list) and len(memory) > 0:
        recent = memory[:3]  # Last 3 entries
        notes = [m.get('note', '') for m in recent if isinstance(m, dict) and m.get('note')]
        if notes:
            context_parts.append(f"Πρόσφατες σημειώσεις: {'; '.join(notes)}")
    
    if not context_parts:
        return ""
    
    return "\n\n📋 ΠΡΟΣΩΠΙΚΑ ΙΑΤΡΙΚΑ ΔΕΔΟΜΕΝΑ ΧΡΗΣΤΗ:\n" + "\n".join(context_parts) + "\n\nΧρησιμοποίησε αυτά τα στοιχεία για να δώσεις προσωποποιημένες απαντήσεις."

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "autoanosis-ai-backend",
        "version": "3.0.0",
        "features": ["medical_snapshot", "session_memory", "rate_limiting"]
    }), 200

@app.route('/chat', methods=['POST'])
def chat():
    # Cleanup old conversations periodically
    if len(conversation_storage) > 100:
        cleanup_old_conversations()
    
    data = request.json
    user_message = data.get("message")
    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    # Get user_id from identity_token (Token Bridge)
    user_id = None
    identity_token = data.get("identity_token")
    
    if identity_token:
        is_valid, payload, error = verify_identity_token(identity_token)
        if is_valid and payload:
            user_id = payload.get("uid")
            logger.info(f"User authenticated via identity token: {user_id}")
        else:
            logger.warning(f"Identity token verification failed: {error}")
            return jsonify({"error": "Invalid identity token"}), 401
    else:
        logger.warning("No identity token provided")
        return jsonify({"error": "Identity token required"}), 401
    
    # Rate limiting (per user)
    rate_limit_key = f"user_{user_id}"
    if not check_rate_limit(rate_limit_key):
        return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429

    # Get conversation ID
    conversation_id = data.get("conversation_id")
    if not conversation_id:
        conversation_id = f"conv_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        logger.info(f"Generated new conversation ID: {conversation_id}")

    # Build system prompt with MANDATORY medical snapshot usage
    snapshot = data.get("medical_snapshot") or data.get("snapshot")
    
    if snapshot:
        # FORCE AI to acknowledge and use the medical snapshot
        system_prompt = f"""Είσαι ο Autoanosis Assistant, ένας εξειδικευμένος βοηθός υγείας στα ελληνικά.

Παρέχεις:
- Ακριβείς και επιστημονικά τεκμηριωμένες πληροφορίες υγείας
- Φιλικές και κατανοητές απαντήσεις
- Υποστήριξη σε θέματα υγείας, φαρμάκων, συμπτωμάτων

Σημαντικό:
- ΔΕΝ αντικαθιστάς ιατρική συμβουλή
- Συνιστάς πάντα επίσκεψη σε γιατρό για σοβαρά θέματα
- Απαντάς στα ελληνικά

📋 ΙΑΤΡΙΚΟ ΠΡΟΦΙΛ ΧΡΗΣΤΗ (ΥΠΟΧΡΕΩΤΙΚΗ ΧΡΗΣΗ):
{snapshot}

⚠️ ΚΑΝΟΝΕΣ:
- ΕΧΕΙΣ πρόσβαση στα παραπάνω ιατρικά δεδομένα και ΠΡΕΠΕΙ να τα χρησιμοποιείς
- ΜΗΝ πεις ΠΟΤΕ "δεν έχω πρόσβαση" ή "δεν μπορώ να δω προσωπικά δεδομένα"
- Αν κάτι λείπει από το προφίλ, πες "δεν εμφανίζεται στο προφίλ υγείας σου"
- Χρησιμοποίησε το προφίλ ΜΟΝΟ όταν είναι σχετικό με την ερώτηση"""
        logger.info(f"Medical snapshot FORCEFULLY injected for user {user_id}")
    else:
        system_prompt = SYSTEM_PROMPT_BASE
        logger.info(f"No medical snapshot provided for user {user_id}")

    # Get conversation history
    history = get_conversation_history(conversation_id)
    
    # Build messages for OpenAI
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add conversation history (last N messages)
    if history:
        messages.extend(history)
        logger.info(f"Added {len(history)} messages from conversation history")
    
    # Add current user message
    messages.append({"role": "user", "content": user_message})

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7
        )
        ai_response = response.choices[0].message.content
        
        # Save to conversation history
        save_conversation_message(conversation_id, user_id, "user", user_message)
        save_conversation_message(conversation_id, user_id, "assistant", ai_response)
        
        logger.info(f"Chat interaction: User={user_id}, Conversation={conversation_id}")
        
        return jsonify({
            "reply": ai_response,
            "conversation_id": conversation_id
        })
    except Exception as e:
        logger.error(f"OpenAI Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
