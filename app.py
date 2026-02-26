"""
Autoanosis AI Backend v4.1.0
Professional Flask backend for AI Assistant with Medical Context
Deployed on Render.com

Changelog:
v4.1.0 (2026-02-25) - Phase 1+2 Security Hardening
- SECURITY: Disabled frontend snapshot fallback in production (fail-safe)
- SECURITY: Production-safe medical data access (no injection risk)
- AUDIT: Enhanced logging (user_id, source, latency, no PII)
- HARDENING: Fail-safe design - WordPress API failure = safe error
- PRODUCTION: Medical-grade security standards

v4.0.0 (2026-02-25) - WordPress Aggregator Integration
- NEW: Server-to-server WordPress API integration
- NEW: Unified medical context from WordPress Aggregator
- ARCHITECTURE: Clean separation (WordPress API vs frontend snapshot)
- BACKWARD COMPATIBLE: Fallback to frontend snapshot if API unavailable
"""

import os
import logging
import time
import uuid
import requests
from collections import defaultdict
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from identity import verify_identity_token
from ocr_endpoint import ocr_bp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Register OCR blueprint
app.register_blueprint(ocr_bp)

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

# WordPress API Configuration
WORDPRESS_URL = os.environ.get("WORDPRESS_URL", "https://autoanosis.com")
WORDPRESS_API_KEY = os.environ.get("WORDPRESS_API_KEY", "")
WORDPRESS_API_ENABLED = os.environ.get("WORDPRESS_API_ENABLED", "false").lower() == "true"
ALLOW_FRONTEND_SNAPSHOT = os.environ.get("ALLOW_FRONTEND_SNAPSHOT", "false").lower() == "true"

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

def fetch_medical_context_from_wordpress(user_id: int) -> dict:
    """
    Fetch medical context from WordPress Aggregator API
    
    Uses server-to-server bot endpoint: POST /wp-json/autoanosis/v1/bot/medical-context
    """
    if not WORDPRESS_API_ENABLED or not WORDPRESS_API_KEY:
        logger.warning("WordPress API disabled or no API key configured")
        return None
    
    try:
        url = f"{WORDPRESS_URL}/wp-json/autoanosis/v1/bot/medical-context"
        headers = {
            "X-API-Key": WORDPRESS_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {"user_id": user_id}
        
        logger.info(f"Fetching medical context from WordPress for user {user_id}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Successfully fetched medical context for user {user_id}")
            return normalize_wordpress_response(data)
        elif response.status_code == 401:
            logger.error("WordPress API authentication failed - check API key")
            return None
        elif response.status_code == 400:
            logger.error(f"WordPress API bad request: {response.text}")
            return None
        else:
            logger.error(f"WordPress API error {response.status_code}: {response.text}")
            return None
            
    except requests.exceptions.Timeout:
        logger.error("WordPress API request timeout")
        return None
    except requests.exceptions.ConnectionError:
        logger.error("WordPress API connection error")
        return None
    except Exception as e:
        logger.error(f"WordPress API unexpected error: {str(e)}")
        return None

def normalize_wordpress_response(wp_data: dict) -> dict:
    """Normalize WordPress API response to frontend schema
    
    WordPress API returns:
    {
      "subsystems": {
        "medical_memory": {
          "medications": [{"medication_name": "...", "dosage": "..."}]
        }
      },
      "unified": {...}
    }
    
    Frontend expects:
    {
      "autoanosis_medications": [{"name": "..."}],
      "autoanosis_conditions": [...],
      "autoanosis_allergies": [...]
    }
    """
    if not isinstance(wp_data, dict):
        return {}
    
    normalized = {}
    
    # Extract medications from subsystems.medical_memory.medications
    subsystems = wp_data.get('subsystems', {})
    if isinstance(subsystems, dict):
        medical_memory = subsystems.get('medical_memory', {})
        if isinstance(medical_memory, dict):
            medications = medical_memory.get('medications', [])
            if isinstance(medications, list) and len(medications) > 0:
                # Transform to frontend schema
                normalized['autoanosis_medications'] = [
                    {'name': med.get('medication_name', ''), 'dosage': med.get('dosage', '')}
                    for med in medications
                    if isinstance(med, dict) and med.get('medication_name')
                ]
    
    # Try unified as fallback (if subsystems is empty)
    if not normalized.get('autoanosis_medications'):
        unified = wp_data.get('unified', {})
        if isinstance(unified, dict):
            # Check if unified has medications
            unified_meds = unified.get('medications', [])
            if isinstance(unified_meds, list) and len(unified_meds) > 0:
                normalized['autoanosis_medications'] = unified_meds
            
            # Conditions and allergies from unified
            if unified.get('conditions'):
                normalized['autoanosis_conditions'] = unified.get('conditions')
            if unified.get('allergies'):
                normalized['autoanosis_allergies'] = unified.get('allergies')
    
    return normalized

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
    """Enhanced health check with WordPress API reachability test
    
    Returns:
    - 200: All systems operational (including WordPress API if enabled)
    - 503: Critical failure (WordPress API unreachable when enabled)
    """
    health_status = {
        "status": "healthy",
        "service": "autoanosis-ai-backend",
        "version": "4.1.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "features": [
            "wordpress_api_integration",
            "unified_medical_context",
            "fail_safe_medical_access",
            "production_security_hardening",
            "session_memory",
            "rate_limiting",
            "audit_logging"
        ],
        "config": {
            "wordpress_api_enabled": WORDPRESS_API_ENABLED,
            "wordpress_api_url": WORDPRESS_API_URL if WORDPRESS_API_ENABLED else None,
            "allow_frontend_snapshot": ALLOW_FRONTEND_SNAPSHOT,
            "security_level": "production" if not ALLOW_FRONTEND_SNAPSHOT else "development"
        },
        "checks": {
            "env_vars": True,  # If we got here, critical env vars are loaded
            "wordpress_api": None
        }
    }
    
    # Test WordPress API reachability if enabled
    if WORDPRESS_API_ENABLED:
        try:
            # Lightweight ping to WordPress API (no user data)
            url = f"{WORDPRESS_API_URL}"
            headers = {"X-API-Key": WORDPRESS_API_KEY}
            # Use a test user_id that should always exist (admin user_id=1)
            payload = {"user_id": 1}
            
            response = requests.post(url, json=payload, headers=headers, timeout=5)
            
            if response.status_code == 200:
                health_status["checks"]["wordpress_api"] = {
                    "status": "reachable",
                    "latency_ms": int(response.elapsed.total_seconds() * 1000)
                }
            elif response.status_code == 401:
                # API key issue - critical failure
                health_status["status"] = "unhealthy"
                health_status["checks"]["wordpress_api"] = {
                    "status": "auth_failed",
                    "error": "WordPress API authentication failed - check API key"
                }
                logger.error("Health check: WordPress API authentication failed")
                return jsonify(health_status), 503
            else:
                # Other error - critical failure
                health_status["status"] = "unhealthy"
                health_status["checks"]["wordpress_api"] = {
                    "status": "error",
                    "http_status": response.status_code,
                    "error": f"WordPress API returned {response.status_code}"
                }
                logger.error(f"Health check: WordPress API error {response.status_code}")
                return jsonify(health_status), 503
                
        except requests.exceptions.Timeout:
            health_status["status"] = "unhealthy"
            health_status["checks"]["wordpress_api"] = {
                "status": "timeout",
                "error": "WordPress API request timeout (5s)"
            }
            logger.error("Health check: WordPress API timeout")
            return jsonify(health_status), 503
            
        except requests.exceptions.ConnectionError:
            health_status["status"] = "unhealthy"
            health_status["checks"]["wordpress_api"] = {
                "status": "unreachable",
                "error": "WordPress API connection error"
            }
            logger.error("Health check: WordPress API connection error")
            return jsonify(health_status), 503
            
        except Exception as e:
            health_status["status"] = "unhealthy"
            health_status["checks"]["wordpress_api"] = {
                "status": "error",
                "error": f"Unexpected error: {str(e)}"
            }
            logger.error(f"Health check: WordPress API unexpected error: {str(e)}")
            return jsonify(health_status), 503
    else:
        health_status["checks"]["wordpress_api"] = {
            "status": "disabled",
            "note": "WordPress API integration is not enabled"
        }
    
    return jsonify(health_status), 200

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

    # Build system prompt with medical snapshot (if available)
    # Production-safe: WordPress API as source of truth
    snapshot = ""
    snapshot_source = "none"
    start_time = time.time()
    wordpress_api_success = False
    
    # 1. Try WordPress Aggregator API (source of truth)
    if WORDPRESS_API_ENABLED:
        wordpress_context = fetch_medical_context_from_wordpress(user_id)
        if wordpress_context is not None:  # API call succeeded (even if empty data)
            wordpress_api_success = True
            snapshot = build_medical_context(wordpress_context)
            snapshot_source = "wordpress_api"
            latency_ms = int((time.time() - start_time) * 1000)
            if snapshot:
                logger.info(f"Using WordPress API medical context for user {user_id} (latency: {latency_ms}ms)")
            else:
                logger.info(f"WordPress API returned empty medical context for user {user_id} (latency: {latency_ms}ms)")
    
    # 2. Frontend snapshot fallback (ONLY if explicitly enabled AND WordPress API failed)
    # Production default: ALLOW_FRONTEND_SNAPSHOT=false (fail-safe)
    if not wordpress_api_success and ALLOW_FRONTEND_SNAPSHOT:
        frontend_snapshot = data.get("medical_snapshot") or data.get("snapshot")
        if frontend_snapshot:
            snapshot = build_medical_context(frontend_snapshot)
            snapshot_source = "frontend_snapshot"
            logger.warning(f"Using frontend snapshot for user {user_id} (fallback enabled)")
    
    # 3. Fail safely ONLY if WordPress API is enabled but failed to respond
    if WORDPRESS_API_ENABLED and not wordpress_api_success:
        logger.error(f"WordPress API failed for user {user_id} (wordpress_api_enabled={WORDPRESS_API_ENABLED})")
        return jsonify({
            "error": "medical_context_unavailable",
            "reply": "Δεν μπορώ να ανακτήσω με ασφάλεια το ιατρικό σου πλαίσιο αυτή τη στιγμή. Παρακαλώ δοκίμασε ξανά σε λίγο."
        }), 503
    
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
            model="gpt-4o-mini",
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
