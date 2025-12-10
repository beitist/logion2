from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import project, translate
from .database import engine, Base

# Create DB tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Logion 2 API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], # Vite default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(project.router)
app.include_router(translate.router)

@app.get("/")
def read_root():
    return {"message": "Logion 2 Backend Running"}
