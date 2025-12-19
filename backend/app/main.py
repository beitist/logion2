from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import project, translate, segment, glossary
from .database import engine, Base

# Create DB tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Logion 2 API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://localhost:3000",
],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(project.router)
app.include_router(translate.router)
app.include_router(segment.router)
app.include_router(glossary.router)

@app.get("/")
def read_root():
    return {"message": "Logion 2 Backend Running"}

@app.get("/config/models")
def get_ai_models():
    """Returns the list of available AI models from ai_models.json"""
    import os
    import json
    
    # Debugging paths
    base_dir = os.path.dirname(os.path.abspath(__file__)) # .../backend/app
    backend_dir = os.path.dirname(base_dir) # .../backend
    
    candidates = [
        os.path.join(backend_dir, "ai_models.json"), # Expected: .../backend/ai_models.json
        "ai_models.json", # CWD
        "/Users/beiti/prog/logion2/backend/ai_models.json" # Absolute fallback
    ]
    
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    # Inject debug info? No, keep it clean.
                    # data["_source"] = path 
                    return data
            except Exception as e:
                print(f"Failed to read {path}: {e}")
                
    # Fallback
    return {
        "models": [{"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash (Fallback - File Not Found)", "provider": "google"}],
        "debug_searched": candidates
    }
