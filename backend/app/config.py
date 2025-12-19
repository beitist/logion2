import os
import json
from typing import List, Dict, Any

# Locate ai_models.json relative to the backend root or app
# Assuming config.py is in backend/app/
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # backend/app
BACKEND_DIR = os.path.dirname(BASE_DIR) # backend

AI_MODELS_FILE = os.path.join(BACKEND_DIR, "ai_models.json")

def get_ai_models_config() -> Dict[str, Any]:
    """
    Loads the ai_models.json configuration.
    Returns empty dict if file not found or error.
    """
    if not os.path.exists(AI_MODELS_FILE):
        # Fallback if running from a different CWD (e.g. tests)
        # Try CWD/ai_models.json
        cwd_path = "ai_models.json"
        if os.path.exists(cwd_path):
             try:
                with open(cwd_path, "r") as f:
                    return json.load(f)
             except:
                 pass
        return {"models": []}

    try:
        with open(AI_MODELS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {AI_MODELS_FILE}: {e}")
        return {"models": []}

def get_default_model_id() -> str:
    """
    Returns the ID of the first model in ai_models.json.
    Falls back to a safe default if list is empty.
    """
    config = get_ai_models_config()
    models = config.get("models", [])
    if models and len(models) > 0:
        return models[0]["id"]
    
    return "gemini-2.5-flash" # Ultimate hardcoded fallback if config completely missing
