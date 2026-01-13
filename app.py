"""
Autoanosis AI Backend
Professional Flask backend for AI Assistant
Deployed on Render.com
"""

import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import openai

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Configure CORS - allow requests from autoanosis.com
CORS(app, resources={
    r"/chat": {
        "origins": [
            "https://autoanosis.com",
            "https://www.autoanosis.com",
            "http://localhost:*"  # For local testing
        ],
        "methods": ["POST", "OPTIONS"],
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


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render"""
    return jsonify({
        "status": "healthy",
        "service": "autoanosis-ai-backend",
        "version": "1.0.0"
    }), 200


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
