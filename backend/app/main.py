"""Main FastAPI application for Legal AI Vault"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import os
from app.config import config
from app.routes import upload, chat
from app.utils.database import init_db

# Initialize database on startup
init_db()

app = FastAPI(
    title=config.API_TITLE,
    version=config.API_VERSION,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])

# Serve static files from frontend/dist
frontend_dist = Path(__file__).parent.parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dist / "assets")), name="static")
    
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve frontend files, fallback to index.html for SPA routing"""
        # Don't serve API routes
        if full_path.startswith("api/"):
            return {"error": "Not found"}, 404
        
        file_path = frontend_dist / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        
        # For SPA: serve index.html for all non-API routes
        index_path = frontend_dist / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        
        return {"error": "Frontend not built"}, 404


@app.get("/api/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
