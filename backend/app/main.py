"""Main FastAPI application for Legal AI Vault"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
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

# API routes - MUST be registered BEFORE any catch-all routes
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])


@app.get("/api/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok"}


# Debug endpoint to check routes
@app.api_route("/api/debug/routes", methods=["GET"])
async def debug_routes():
    """Debug endpoint to list all routes"""
    routes = []
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            routes.append({
                "path": route.path,
                "methods": list(route.methods),
                "name": getattr(route, "name", "unknown")
            })
    return {"routes": routes}


# Serve static files from frontend/dist
# Path calculation: backend/app/main.py -> backend -> project root -> frontend/dist
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"

if frontend_dist.exists():
    # Mount static assets
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    
    # Serve frontend SPA - ONLY handles GET requests
    # POST/PUT/DELETE requests to /api/* will be handled by API routes above
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str, request: Request):
        """Serve frontend files, fallback to index.html for SPA routing (GET only)"""
        # Safety check: don't serve API routes (shouldn't reach here for GET, but just in case)
        if full_path.startswith("api/"):
            return JSONResponse(
                {"error": "Not found", "method": request.method, "path": full_path},
                status_code=404
            )
        
        # Don't serve assets (already mounted)
        if full_path.startswith("assets/"):
            return JSONResponse({"error": "Not found"}, status_code=404)
        
        # Try to serve the requested file
        file_path = frontend_dist / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        
        # For SPA: serve index.html for all non-API routes
        index_path = frontend_dist / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        
        return JSONResponse(
            {"error": "Frontend not built. Please run: cd frontend && npm install && npm run build"},
            status_code=404
        )
else:
    # Frontend not built - show helpful message
    @app.get("/")
    async def root():
        """Root endpoint - frontend not built"""
        return {
            "message": "Legal AI Vault API",
            "note": "Frontend not built. Build it with: cd frontend && npm install && npm run build",
            "api_endpoints": {
                "health": "/api/health",
                "upload": "/api/upload",
                "chat": "/api/chat"
            }
        }


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
