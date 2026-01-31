"""Main FastAPI application for Legal AI Vault"""
# #region agent log - EARLY LOGGING BEFORE ANY IMPORTS
import sys
import json
from datetime import datetime
try:
    log_entry = json.dumps({
        "sessionId": "debug-session",
        "runId": "startup",
        "hypothesisId": "EARLY",
        "location": "main.py:1",
        "message": "VERY EARLY: Before any imports",
        "data": {"step": "very_early_start"},
        "timestamp": int(datetime.now().timestamp() * 1000)
    })
    # Print to both stderr and stdout, multiple times for visibility
    for stream in [sys.stderr, sys.stdout]:
        for _ in range(2):
            print(f"[DEBUG] {log_entry}", file=stream, flush=True)
    with open('/tmp/debug.log', 'a') as f:
        f.write(log_entry + '\n')
except Exception as e:
    try:
        for stream in [sys.stderr, sys.stdout]:
            for _ in range(2):
                print(f"[DEBUG] EARLY LOG FAILED: {e}", file=stream, flush=True)
    except: pass
# #endregion

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from pathlib import Path
import os
import logging
import sys
from datetime import datetime
import json
import traceback

# #region agent log
def _debug_log(location, message, data, hypothesis_id="A", run_id="startup"):
    """Write debug log to stderr (Docker captures) and /tmp/debug.log"""
    log_entry = json.dumps({
        "sessionId": "debug-session",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(datetime.now().timestamp() * 1000)
    })
    try:
        # Write to stderr (Docker captures this)
        print(f"[DEBUG] {log_entry}", file=sys.stderr, flush=True)
        # Also write to container path
        with open('/tmp/debug.log', 'a') as f:
            f.write(log_entry + '\n')
    except: pass

try:
    _debug_log("main.py:1", "Module import started", {"step": "import_start"})
except: pass
# #endregion

# Version info for deployment tracking
APP_VERSION = "6.0.0"
APP_BUILD_DATE = "2026-01-29"
APP_COMMIT = "039f731"  # feat: Add Reflection Pattern and Citation Verification

# #region agent log
try:
    _debug_log("main.py:18", "Before config import", {"step": "before_config"})
except: pass
# #endregion

try:
    from app.config import config
    # #region agent log
    try:
        _debug_log("main.py:21", "Config imported successfully", {"step": "config_imported", "has_db_url": bool(os.getenv("DATABASE_URL"))})
    except: pass
    # #endregion
except Exception as e:
    # #region agent log
    try:
        _debug_log("main.py:21", "Config import failed", {"step": "config_import_error", "error": str(e), "error_type": type(e).__name__}, hypothesis_id="A")
    except: pass
    # #endregion
    raise
from app.routes import upload, chat, auth, cases, dashboard, analysis, reports, settings, websocket, tabular_review, prompts, workflows, folders, review_table, assistant_chat, assistant_chat_v2, workflow_execution, plan_execution, metrics, document_editor, playbooks, workflow_agentic, health
from app.utils.database import init_db

# Core modules
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging, RequestLoggingMiddleware
from app.core.rate_limiter import RateLimitMiddleware

# Configure structured logging
is_production = os.getenv("ENVIRONMENT", "development") == "production"
setup_logging(
    level=os.getenv("LOG_LEVEL", "INFO"),
    json_format=is_production
)

logger = logging.getLogger(__name__)

# Initialize database on startup
logger.info("Initializing database...")
# #region agent log
try:
    _debug_log("main.py:36", "Before init_db", {"step": "before_init_db", "db_url_present": bool(os.getenv("DATABASE_URL"))}, hypothesis_id="B")
except: pass
# #endregion
try:
    init_db()
    logger.info("Database initialized successfully")
    # #region agent log
    try:
        _debug_log("main.py:40", "init_db succeeded", {"step": "init_db_success"}, hypothesis_id="B")
    except: pass
    # #endregion
except Exception as e:
    error_msg = f"❌ Failed to initialize database: {e}"
    logger.error(error_msg, exc_info=True)
    # #region agent log
    try:
        _debug_log("main.py:126", "init_db failed", {"step": "init_db_error", "error": str(e), "error_type": type(e).__name__, "traceback": traceback.format_exc()}, hypothesis_id="B")
    except: pass
    # #endregion
    # Print to both stderr and stdout for visibility
    import sys
    for stream in [sys.stderr, sys.stdout]:
        for _ in range(3):
            print(f"\n{'='*80}\n{error_msg}\n{'='*80}\n", file=stream, flush=True)
    raise

# #region agent log
try:
    _debug_log("main.py:45", "Before FastAPI app creation", {"step": "before_app_creation"}, hypothesis_id="C")
except: pass
# #endregion

app = FastAPI(
    title=config.API_TITLE,
    version=config.API_VERSION,
)

# #region agent log
try:
    _debug_log("main.py:49", "FastAPI app created", {"step": "app_created"}, hypothesis_id="C")
except: pass
# #endregion

# Обработчик ошибок валидации
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Обработчик ошибок валидации Pydantic"""
    errors = []
    for error in exc.errors():
        field = " -> ".join(str(loc) for loc in error.get("loc", []))
        msg = error.get("msg", "Validation error")
        errors.append(f"{field}: {msg}")
    
    error_message = "; ".join(errors) if errors else "Validation error"
    logger.warning(f"Validation error: {error_message}")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": error_message,
            "errors": exc.errors()
        }
)

# Add request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests"""
    start_time = datetime.utcnow()
    
    # Skip logging HEAD requests (usually health checks)
    is_head_request = request.method == "HEAD"
    
    if not is_head_request:
        # Log request
        logger.info(
            f"Request: {request.method} {request.url.path}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "client": request.client.host if request.client else None,
            }
        )
    
    try:
        response = await call_next(request)
        process_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Skip logging HEAD requests with 405 (Method Not Allowed is expected for HEAD)
        if not (is_head_request and response.status_code == 405):
            # Log response
            logger.info(
                f"Response: {request.method} {request.url.path} - {response.status_code} ({process_time:.3f}s)",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "process_time": process_time,
                }
            )
        
        # Add CSP header at the end to ensure it's not overwritten
        if "Content-Security-Policy" not in response.headers:
            csp_policy = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-eval' 'unsafe-inline' https: http:; "
                "style-src 'self' 'unsafe-inline' https: http: data:; "
                "img-src 'self' data: blob: https: http:; "
                "font-src 'self' data: blob: https: http:; "
                "connect-src 'self' blob: https: http:; "
                "worker-src 'self' blob:; "
                "frame-src 'self' https: http:; "
                "object-src 'self' blob:;"
            )
            response.headers["Content-Security-Policy"] = csp_policy
        return response
    except Exception as e:
        process_time = (datetime.utcnow() - start_time).total_seconds()
        logger.error(
            f"Error processing request: {request.method} {request.url.path} - {str(e)} ({process_time:.3f}s)",
            extra={
                "method": request.method,
                "path": request.url.path,
                "error": str(e),
                "process_time": process_time,
            },
            exc_info=True
        )
        raise

# Metrics middleware (tracking request metrics)
from app.middleware.metrics import MetricsMiddleware
app.add_middleware(MetricsMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSP middleware to allow unsafe-eval for docx-preview (runs after all other middleware)
@app.middleware("http")
async def add_csp_header(request: Request, call_next):
    """Add Content-Security-Policy header to allow unsafe-eval for docx-preview library"""
    response = await call_next(request)
    # Force set CSP header (overwrite if exists) to ensure docx-preview works
    # More permissive CSP to allow docx-preview and other libraries to work
    csp_policy = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-eval' 'unsafe-inline' https: http:; "
        "style-src 'self' 'unsafe-inline' https: http: data:; "
        "img-src 'self' data: blob: https: http:; "
        "font-src 'self' data: blob: https: http:; "
        "connect-src 'self' blob: https: http:; "
        "worker-src 'self' blob:; "
        "frame-src 'self' https: http:; "
        "object-src 'self' blob:;"
    )
    response.headers["Content-Security-Policy"] = csp_policy
    return response

# API routes - MUST be registered BEFORE any catch-all routes
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(cases.router, prefix="/api/cases", tags=["cases"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(assistant_chat.router, tags=["assistant-chat"])
app.include_router(assistant_chat_v2.router, tags=["assistant-chat-v2"])
app.include_router(websocket.router, tags=["websocket"])
app.include_router(tabular_review.router, prefix="/api/tabular-review", tags=["tabular-review"])
app.include_router(review_table.router, prefix="/api/review-table", tags=["review-table"])
app.include_router(prompts.router, prefix="/api", tags=["prompts"])
app.include_router(workflows.router, prefix="/api", tags=["workflows"])
# IMPORTANT: workflow_agentic MUST be before workflow_execution to prevent /workflow-agentic/* being matched by /{workflow_id}/*
app.include_router(workflow_agentic.router, prefix="/api", tags=["workflow-agentic"])
app.include_router(workflow_execution.router, prefix="/api", tags=["workflow-execution"])
app.include_router(folders.router, prefix="/api", tags=["folders"])
app.include_router(plan_execution.router, prefix="/api/plan", tags=["plan-execution"])
app.include_router(metrics.router, prefix="/api/metrics", tags=["metrics"])
app.include_router(document_editor.router, prefix="/api/documents-editor", tags=["document-editor"])
# Playbooks router (all endpoints unified in one router with correct ordering)
app.include_router(playbooks.router, prefix="/api", tags=["playbooks"])
# Health endpoints (includes detailed health checks and metrics)
app.include_router(health.router, tags=["health"])

# Register custom exception handlers
register_exception_handlers(app)


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
            response = FileResponse(str(index_path))
            # Ensure CSP header is set for HTML files
            csp_policy = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-eval' 'unsafe-inline' https: http:; "
                "style-src 'self' 'unsafe-inline' https: http: data:; "
                "img-src 'self' data: blob: https: http:; "
                "font-src 'self' data: blob: https: http:; "
                "connect-src 'self' blob: https: http:; "
                "worker-src 'self' blob:; "
                "frame-src 'self' https: http:; "
                "object-src 'self' blob:;"
            )
            response.headers["Content-Security-Policy"] = csp_policy
            return response
        
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


# Version endpoint for deployment tracking
@app.get("/api/version")
async def get_version():
    """Get current application version and build info"""
    return {
        "version": APP_VERSION,
        "commit": APP_COMMIT,
        "build_date": APP_BUILD_DATE,
        "chat_orchestrator": "v5.0 (ReActChatAgent)",
        "features": [
            "ReAct Agent with 11+ tools",
            "ГАРАНТ integration",
            "Deep Think (7 phases)",
            "Reflection Pattern",
            "Citation Verification"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    import os
    # #region agent log
    try:
        port = int(os.getenv("PORT", 8000))
        _debug_log("main.py:307", "Starting uvicorn", {"step": "uvicorn_start", "port": port, "port_env": os.getenv("PORT")}, hypothesis_id="D")
    except Exception as e:
        _debug_log("main.py:307", "Port setup error", {"step": "port_error", "error": str(e)}, hypothesis_id="D")
        port = 8000
    # #endregion
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
