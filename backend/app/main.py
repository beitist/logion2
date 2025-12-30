from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from .routers import project, translate, segment, glossary
from .database import engine, Base
from .logger import main_logger, correlation_id_ctx
import uuid
import structlog

# Create DB tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Logion 2 API")

# Middleware: Correlation ID
from .middleware.correlation import CorrelationMiddleware, get_request_id

app.add_middleware(CorrelationMiddleware)

# Global Exception Handler


from .core.exceptions import LogionException, ProjectNotFound, ModelError

# ...

# Custom Exception Handlers
@app.exception_handler(ProjectNotFound)
async def project_not_found_handler(request: Request, exc: ProjectNotFound):
    return JSONResponse(
        status_code=404,
        content={"detail": exc.message, "request_id": get_request_id()}
    )

@app.exception_handler(ModelError)
async def model_error_handler(request: Request, exc: ModelError):
    main_logger.error("model_failure", error=str(exc))
    return JSONResponse(
        status_code=503,
        content={"detail": "AI Model Unavailable", "reason": exc.message, "request_id": correlation_id_ctx.get()}
    )

@app.exception_handler(LogionException)
async def domain_exception_handler(request: Request, exc: LogionException):
    main_logger.warning("domain_exception", error=str(exc), details=exc.details)
    return JSONResponse(
        status_code=400,
        content={"detail": exc.message, "details": exc.details, "request_id": correlation_id_ctx.get()}
    )

# Global Exception Handler (Catch-All)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log the full exception with stack trace
    # Structlog's format_exc_info will capture the trace
    main_logger.exception("unhandled_exception", error=str(exc))
    
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal Server Error",
            "request_id": correlation_id_ctx.get()
        }
    )

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
