# Autoanosis AI Backend

Professional Flask backend for Autoanosis AI Assistant, deployed on Render.com.

## Architecture

```
User → WordPress Chat Widget → POST /chat → Render Backend → OpenAI API → Response
```

## Features

- ✅ Single `/chat` endpoint (POST)
- ✅ CORS configured for autoanosis.com
- ✅ Professional error handling
- ✅ Logging for debugging
- ✅ Health check endpoint
- ✅ Production-ready with Gunicorn

## API

### POST /chat

**Request:**
```json
{
  "message": "Τι είναι η υπέρταση;"
}
```

**Response:**
```json
{
  "response": "Η υπέρταση είναι..."
}
```

## Deployment on Render

### Step 1: Create GitHub Repository

1. Go to GitHub and create a new repository: `autoanosis-ai-backend`
2. Upload these files:
   - `app.py`
   - `requirements.txt`
   - `render.yaml`
   - `README.md`

### Step 2: Deploy on Render

1. Go to [Render Dashboard](https://dashboard.render.com/)
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repository
4. Render will auto-detect the configuration from `render.yaml`
5. Add environment variable:
   - **Key:** `OPENAI_API_KEY`
   - **Value:** Your OpenAI API key
6. Click **"Create Web Service"**

### Step 3: Get Public URL

After deployment, you'll get a URL like:
```
https://autoanosis-ai-backend.onrender.com
```

### Step 4: Update WordPress

Update the WordPress Assistant v2 UI plugin to use:
```
https://autoanosis-ai-backend.onrender.com/chat
```

## Testing

Test the endpoint with curl:

```bash
curl -X POST https://autoanosis-ai-backend.onrender.com/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Γεια σου"}'
```

Expected response:
```json
{
  "response": "Γεια σου! Πώς μπορώ να σε βοηθήσω σήμερα;"
}
```

## Environment Variables

- `OPENAI_API_KEY` - Your OpenAI API key (required)
- `PORT` - Port number (auto-set by Render)
- `PYTHON_VERSION` - Python version (3.11.0)

## Logs

View logs in Render Dashboard → Your Service → Logs

## Support

For issues or questions, contact the Autoanosis team.
