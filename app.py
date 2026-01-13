"""
Autoanosis AI Backend
Professional Flask backend for AI Assistant
Deployed on Render.com
"""

import os
import logging
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import openai

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Configure CORS - allow requests from autoanosis.com
CORS(app, resources={
    r"/*": {
        "origins": [
            "https://autoanosis.com",
            "https://www.autoanosis.com",
            "http://localhost:*"  # For local testing
        ],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# Configure OpenAI API key (old style)
openai.api_key = os.environ.get("OPENAI_API_KEY")

# System prompt for Autoanosis health assistant
SYSTEM_PROMPT = """Είσαι ο Autoanosis Assistant, ένας εξειδικευμένος βοηθός υγείας στα ελληνικά.

Παρέχεις:
- Ακριβείς και επιστημονικά τεκμηριωμένες πληροφορίες υγείας
- Φιλικές και κατανοητές απαντήσεις
- Υποστήριξη σε θέματα υγείας, φαρμάκων, συμπτωμάτων

Σημαντικό:
- ΔΕΝ αντικαθιστάς ιατρική συμβουλή
- Συνιστάς πάντα επίσκεψη σε γιατρό για σοβαρά θέματα
- Απαντάς στα ελληνικά"""

# Chat UI HTML Template
CHAT_UI_HTML = """
<!DOCTYPE html>
<html lang="el">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Autoanosis Assistant</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        .chat-header {
            background: white;
            padding: 20px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        .chat-header h1 {
            color: #667eea;
            font-size: 24px;
            margin-bottom: 5px;
        }
        
        .chat-header p {
            color: #666;
            font-size: 14px;
        }
        
        .chat-messages {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        
        .message {
            display: flex;
            gap: 10px;
            max-width: 80%;
            animation: slideIn 0.3s ease;
        }
        
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .message.user {
            align-self: flex-end;
            flex-direction: row-reverse;
        }
        
        .message.bot {
            align-self: flex-start;
        }
        
        .message-content {
            background: white;
            padding: 12px 16px;
            border-radius: 18px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            line-height: 1.5;
        }
        
        .message.user .message-content {
            background: #667eea;
            color: white;
        }
        
        .message.bot .message-content {
            background: white;
            color: #333;
        }
        
        .chat-input-container {
            background: white;
            padding: 20px;
            box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
        }
        
        .chat-input-wrapper {
            display: flex;
            gap: 10px;
            max-width: 800px;
            margin: 0 auto;
        }
        
        .chat-input {
            flex: 1;
            padding: 12px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 24px;
            font-size: 15px;
            outline: none;
            transition: border-color 0.3s;
        }
        
        .chat-input:focus {
            border-color: #667eea;
        }
        
        .chat-send {
            padding: 12px 24px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 24px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.3s;
        }
        
        .chat-send:hover:not(:disabled) {
            background: #5568d3;
        }
        
        .chat-send:disabled {
            background: #ccc;
            cursor: not-allowed;
        }
        
        .typing-indicator {
            display: none;
            align-items: center;
            gap: 5px;
            padding: 12px 16px;
            background: white;
            border-radius: 18px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            max-width: fit-content;
        }
        
        .typing-indicator.active {
            display: flex;
        }
        
        .typing-dot {
            width: 8px;
            height: 8px;
            background: #667eea;
            border-radius: 50%;
            animation: typing 1.4s infinite;
        }
        
        .typing-dot:nth-child(2) {
            animation-delay: 0.2s;
        }
        
        .typing-dot:nth-child(3) {
            animation-delay: 0.4s;
        }
        
        @keyframes typing {
            0%, 60%, 100% {
                transform: translateY(0);
            }
            30% {
                transform: translateY(-10px);
            }
        }
        
        .welcome-message {
            text-align: center;
            color: white;
            padding: 40px 20px;
        }
        
        .welcome-message h2 {
            font-size: 28px;
            margin-bottom: 10px;
        }
        
        .welcome-message p {
            font-size: 16px;
            opacity: 0.9;
        }
    </style>
</head>
<body>
    <div class="chat-header">
        <h1>🤖 Autoanosis Assistant</h1>
        <p>Ο ψηφιακός σας βοηθός για θέματα υγείας</p>
    </div>
    
    <div class="chat-messages" id="chat-messages">
        <div class="welcome-message">
            <h2>Γεια σας! 👋</h2>
            <p>Πώς μπορώ να σας βοηθήσω σήμερα;</p>
        </div>
    </div>
    
    <div class="chat-input-container">
        <div class="chat-input-wrapper">
            <input 
                type="text" 
                class="chat-input" 
                id="chat-input" 
                placeholder="Γράψτε την ερώτησή σας..."
                autocomplete="off"
            >
            <button class="chat-send" id="chat-send">Αποστολή</button>
        </div>
    </div>
    
    <script>
        const API_ENDPOINT = '/chat';
        const chatInput = document.getElementById('chat-input');
        const chatSend = document.getElementById('chat-send');
        const chatMessages = document.getElementById('chat-messages');
        
        // Remove welcome message on first interaction
        let firstMessage = true;
        
        async function sendMessage() {
            const message = chatInput.value.trim();
            if (!message) return;
            
            // Remove welcome message
            if (firstMessage) {
                chatMessages.innerHTML = '';
                firstMessage = false;
            }
            
            // Add user message
            addMessage(message, 'user');
            chatInput.value = '';
            chatSend.disabled = true;
            
            // Show typing indicator
            const typingIndicator = document.createElement('div');
            typingIndicator.className = 'typing-indicator active';
            typingIndicator.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
            chatMessages.appendChild(typingIndicator);
            chatMessages.scrollTop = chatMessages.scrollHeight;
            
            try {
                const response = await fetch(API_ENDPOINT, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message })
                });
                
                const data = await response.json();
                
                // Remove typing indicator
                typingIndicator.remove();
                
                if (response.ok) {
                    addMessage(data.response || 'Συγγνώμη, κάτι πήγε στραβά.', 'bot');
                } else {
                    addMessage('Συγγνώμη, δεν μπόρεσα να επεξεργαστώ το αίτημά σας.', 'bot');
                }
            } catch (error) {
                // Remove typing indicator
                typingIndicator.remove();
                addMessage('Συγγνώμη, δεν μπόρεσα να επικοινωνήσω με τον server.', 'bot');
            } finally {
                chatSend.disabled = false;
                chatInput.focus();
            }
        }
        
        function addMessage(text, type) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${type}`;
            messageDiv.innerHTML = `<div class="message-content">${text}</div>`;
            chatMessages.appendChild(messageDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
        
        chatSend.addEventListener('click', sendMessage);
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendMessage();
        });
        
        // Focus input on load
        chatInput.focus();
    </script>
</body>
</html>
"""


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render"""
    return jsonify({
        "status": "healthy",
        "service": "autoanosis-ai-backend",
        "version": "1.0.0"
    }), 200


@app.route('/ui', methods=['GET'])
def chat_ui():
    """
    Chat UI endpoint
    Returns HTML page with chat interface
    """
    return render_template_string(CHAT_UI_HTML)


@app.route('/chat', methods=['POST', 'OPTIONS'])
def chat():
    """
    Main chat endpoint
    Accepts: {"message": "user question"}
    Returns: {"response": "AI answer"}
    """
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        # Get request data
        data = request.get_json()
        
        if not data or 'message' not in data:
            logger.warning("Missing 'message' in request")
            return jsonify({
                "error": "Missing 'message' field"
            }), 400
        
        user_message = data['message'].strip()
        
        if not user_message:
            logger.warning("Empty message received")
            return jsonify({
                "error": "Message cannot be empty"
            }), 400
        
        logger.info(f"Processing chat request: {user_message[:50]}...")
        
        # Call OpenAI API (old style - v0.28.1)
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
            max_tokens=1000
        )
        
        # Extract AI response
        ai_response = response.choices[0].message.content
        
        logger.info(f"Successfully generated response: {ai_response[:50]}...")
        
        return jsonify({
            "response": ai_response
        }), 200
        
    except Exception as e:
        logger.error(f"Error processing chat request: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Internal server error",
            "message": str(e)
        }), 500


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        "error": "Endpoint not found"
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {str(error)}", exc_info=True)
    return jsonify({
        "error": "Internal server error"
    }), 500


if __name__ == '__main__':
    # Get port from environment variable (Render provides this)
    port = int(os.environ.get('PORT', 5000))
    
    # Run Flask app
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False  # Never use debug=True in production
    )
