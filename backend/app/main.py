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
    try:
        import json
        with open("ai_models.json", "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading models: {e}")
        # Fallback if file missing
        return {"models": [{"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash (Fallback)", "provider": "google"}]}
