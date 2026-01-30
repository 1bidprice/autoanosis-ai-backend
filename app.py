"""
Autoanosis AI Backend
Professional Flask backend for AI Assistant
Deployed on Render.com
"""

import os
import logging
import time
import requests
import base64
import json
import hmac
import hashlib
from collections import defaultdict
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from openai import OpenAI
from identity import verify_identity_token, get_user_id_from_token

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

# Configure OpenAI client (new style)
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# WordPress Configuration
WP_BASE_URL = "https://autoanosis.com/wp-json"
WP_MEDICAL_API_KEY = os.environ.get("WP_MEDICAL_API_KEY", "xqx5eWXnPEaNoFZKfChDLVYYp4uBLt8L")

# Token Bridge Configuration
TOKEN_SECRET = os.environ.get("AUTOA_TOKEN_SECRET", "CHANGE_THIS_SECRET")

# Rate limiting storage (in-memory for now)
rate_limit_storage = defaultdict(list)
RATE_LIMIT_GUEST = 10  # 10 requests per hour for guests
RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds

# Medical Context Cache (in-memory)
medical_context_cache = {}
CACHE_TTL = 300  # 5 minutes in seconds

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

# Chat UI HTML Template (with close button and disclaimer)
CHAT_UI_HTML = """
<!DOCTYPE html>
<html lang="el">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Autoanosis Assistant</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
        .chat-header { background: white; padding: 15px 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; z-index: 10; }
        .header-content { flex: 1; }
        .chat-header h1 { color: #667eea; font-size: 18px; margin-bottom: 2px; }
        .chat-header p { color: #666; font-size: 11px; }
        .close-button { background: #f5f5f5; border: none; width: 30px; height: 30px; border-radius: 50%; cursor: pointer; font-size: 16px; color: #666; display: flex; align-items: center; justify-content: center; transition: all 0.3s; }
        .close-button:hover { background: #e0e0e0; color: #333; }
        .disclaimer { background: #fff3cd; border-left: 4px solid #ffc107; padding: 10px 15px; font-size: 11px; color: #856404; line-height: 1.4; }
        .chat-messages { flex: 1; overflow-y: auto; padding: 15px; display: flex; flex-direction: column; gap: 12px; background: rgba(255,255,255,0.05); }
        .message { display: flex; gap: 10px; max-width: 85%; animation: slideIn 0.3s ease; }
        @keyframes slideIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .message.user { align-self: flex-end; flex-direction: row-reverse; }
        .message.bot { align-self: flex-start; }
        .message-content { background: white; padding: 10px 14px; border-radius: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); line-height: 1.5; font-size: 14px; white-space: pre-wrap; }
        .message.user .message-content { background: #667eea; color: white; border-bottom-right-radius: 2px; }
        .message.bot .message-content { background: white; color: #333; border-bottom-left-radius: 2px; }
        .chat-input-container { background: white; padding: 12px 15px; box-shadow: 0 -2px 10px rgba(0,0,0,0.1); }
        .chat-input-wrapper { display: flex; gap: 8px; }
        .chat-input { flex: 1; padding: 10px 15px; border: 1px solid #e0e0e0; border-radius: 20px; font-size: 14px; outline: none; transition: border-color 0.3s; }
        .chat-input:focus { border-color: #667eea; }
        .chat-send { padding: 8px 18px; background: #667eea; color: white; border: none; border-radius: 20px; font-size: 14px; font-weight: 600; cursor: pointer; transition: background 0.3s; }
        .chat-send:hover:not(:disabled) { background: #5568d3; }
        .chat-send:disabled { background: #ccc; cursor: not-allowed; }
        .typing-indicator { display: none; align-items: center; gap: 4px; padding: 10px 14px; background: white; border-radius: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); max-width: fit-content; }
        .typing-indicator.active { display: flex; }
        .typing-dot { width: 6px; height: 6px; background: #667eea; border-radius: 50%; animation: typing 1.4s infinite; }
        .typing-dot:nth-child(2) { animation-delay: 0.2s; }
        .typing-dot:nth-child(3) { animation-delay: 0.4s; }
        @keyframes typing { 0%, 60%, 100% { transform: translateY(0); } 30% { transform: translateY(-6px); } }
        .error-message { background: #f8d7da; color: #721c24; padding: 10px 14px; border-radius: 15px; font-size: 13px; max-width: 85%; align-self: flex-start; }
    </style>
</head>
<body>
    <div class="chat-header">
        <div class="header-content">
            <h1>🤖 Autoanosis Assistant</h1>
            <p>Ο ψηφιακός σας βοηθός υγείας</p>
        </div>
        <button class="close-button" onclick="closeChat()">✕</button>
    </div>
    <div class="disclaimer">
        ⚠️ <b>Προσοχή:</b> Οι απαντήσεις παράγονται από AI και δεν αποτελούν ιατρική συμβουλή. Συμβουλευτείτε πάντα τον γιατρό σας.
    </div>
    <div class="chat-messages" id="chat-messages">
        <div class="message bot">
            <div class="message-content">Γεια σας! 👋 Είμαι ο Autoanosis Assistant. Πώς μπορώ να σας βοηθήσω σήμερα;</div>
        </div>
    </div>
    <div class="chat-input-container">
        <div class="chat-input-wrapper">
            <input type="text" class="chat-input" id="chat-input" placeholder="Γράψτε την ερώτησή σας..." autocomplete="off">
            <button class="chat-send" id="chat-send">Αποστολή</button>
        </div>
    </div>
    <script>
        const chatInput = document.getElementById('chat-input');
        const chatSend = document.getElementById('chat-send');
        const chatMessages = document.getElementById('chat-messages');
        function closeChat() { window.parent.postMessage('closeAutoa', '*'); }
        async function sendMessage() {
            const message = chatInput.value.trim();
            if (!message) return;
            addMessage(message, 'user');
            chatInput.value = '';
            chatSend.disabled = true;
            const typingIndicator = document.createElement('div');
            typingIndicator.className = 'typing-indicator active';
            typingIndicator.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
            chatMessages.appendChild(typingIndicator);
            chatMessages.scrollTop = chatMessages.scrollHeight;
            try {
                const response = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message })
                });
                const data = await response.json();
                typingIndicator.remove();
                if (response.ok) { addMessage(data.response, 'bot'); }
                else { addError(data.error || 'Σφάλμα επεξεργασίας.'); }
            } catch (error) {
                typingIndicator.remove();
                addError('Σφάλμα σύνδεσης με τον server.');
            } finally {
                chatSend.disabled = false;
                chatInput.focus();
            }
        }
        function addMessage(text, type) {
            const div = document.createElement('div');
            div.className = `message ${type}`;
            div.innerHTML = `<div class="message-content">${text}</div>`;
            chatMessages.appendChild(div);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
        function addError(text) {
            const div = document.createElement('div');
            div.className = 'error-message';
            div.textContent = text;
            chatMessages.appendChild(div);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
        chatSend.addEventListener('click', sendMessage);
        chatInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(); });
        chatInput.focus();
    </script>
</body>
</html>
"""

def verify_token(token: str) -> int:
    """
    Verify JWT-like token signed by WordPress
    Token format: base64(payload).signature
    Returns: user_id if valid, raises exception if invalid
    """
    try:
        if not token or '.' not in token:
            raise ValueError("Invalid token format")
        
        data_b64, sig = token.rsplit('.', 1)
        data_json = base64.b64decode(data_b64).decode('utf-8')
        
        # Verify signature
        expected_sig = hmac.new(
            TOKEN_SECRET.encode('utf-8'),
            data_json.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(sig, expected_sig):
            logger.warning(f"Token signature mismatch")
            raise ValueError("Invalid token signature")
        
        # Parse payload
        payload = json.loads(data_json)
        
        # Check expiration
        if payload.get('exp', 0) < time.time():
            logger.warning(f"Token expired")
            raise ValueError("Token expired")
        
        user_id = int(payload.get('uid', 0))
        if user_id <= 0:
            raise ValueError("Invalid user_id in token")
        
        logger.info(f"Token verified for user {user_id}")
        return user_id
    
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise ValueError(f"Token verification failed: {str(e)}")

def check_rate_limit(identifier):
    current_time = time.time()
    rate_limit_storage[identifier] = [t for t in rate_limit_storage[identifier] if current_time - t < RATE_LIMIT_WINDOW]
    if len(rate_limit_storage[identifier]) >= RATE_LIMIT_GUEST:
        return False
    rate_limit_storage[identifier].append(current_time)
    return True

def get_medical_context(user_id):
    """
    Fetch medical context from WordPress REST API with caching
    Cache TTL: 5 minutes
    """
    if not user_id:
        return None
    
    # Check cache first
    cache_key = f"user_{user_id}"
    current_time = time.time()
    
    if cache_key in medical_context_cache:
        cached_data, cached_time = medical_context_cache[cache_key]
        if current_time - cached_time < CACHE_TTL:
            logger.info(f"Medical context cache HIT for user {user_id}")
            return cached_data
        else:
            logger.info(f"Medical context cache EXPIRED for user {user_id}")
    
    # Fetch from WordPress API
    try:
        endpoint = f"{WP_BASE_URL}/autoa/v1/medical-context/{user_id}"
        headers = {"X-API-Key": WP_MEDICAL_API_KEY}
        
        logger.info(f"Fetching medical context from: {endpoint}")
        response = requests.get(endpoint, headers=headers, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                context = data.get('context', '')
                # Cache the result
                medical_context_cache[cache_key] = (context, current_time)
                logger.info(f"Medical context fetched and cached for user {user_id}")
                return context
            else:
                logger.warning(f"Medical context API returned success=false for user {user_id}")
        else:
            logger.error(f"Medical context API returned status {response.status_code} for user {user_id}")
    except Exception as e:
        logger.error(f"Error fetching medical context for user {user_id}: {e}")
    
    return None

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "autoanosis-ai-backend", "version": "2.0.0"}), 200

@app.route('/ui')
def ui():
    return render_template_string(CHAT_UI_HTML)

@app.route('/chat', methods=['POST'])
def chat():
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
    
    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if not check_rate_limit(user_ip):
        return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429

    system_prompt = SYSTEM_PROMPT_BASE
    
    # Fetch Medical Context if user is authenticated
    if user_id:
        logger.info(f"Fetching medical context for user_id: {user_id}")
        medical_context = get_medical_context(user_id)
        if medical_context:
            system_prompt += f"\n\n{medical_context}\n\nΧρησιμοποίησε αυτά τα στοιχεία για να δώσεις προσωποποιημένες απαντήσεις."
            logger.info(f"Medical context injected for user {user_id}")
        else:
            logger.warning(f"Medical context not available for user {user_id}")
    else:
        logger.info("No valid token provided - using guest mode")

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7
        )
        ai_response = response.choices[0].message.content
        logger.info(f"Chat interaction: IP={user_ip}, User={user_id or 'guest'}")
        return jsonify({"response": ai_response})
    except Exception as e:
        logger.error(f"OpenAI Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
