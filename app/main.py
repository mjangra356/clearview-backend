"""FastAPI Application Entrypoint for ClearView Fraud & Compliance Intelligence.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.core.config import settings
from app.api.routes import router
from app.services.ch_client import ch_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ClearView Fraud & Compliance Backend...")
    logger.info(f"Using Companies House API at: {settings.COMPANIES_HOUSE_BASE_URL}")
    yield
    logger.info("Shutting down backend, closing HTTP clients...")
    await ch_client.close()

app = FastAPI(
    title="ClearView — Fraud & Compliance Intelligence API",
    description="Real-time corporate fraud and AML compliance intelligence powered directly by Companies House data.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for frontend UI access (e.g. Next.js on port 3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict to frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sanitize repeated slashes in incoming request URLs (e.g. //companies -> /companies)
@app.middleware("http")
async def normalize_double_slashes(request, call_next):
    raw_path = request.scope.get("path", "")
    if "//" in raw_path:
        import re
        request.scope["path"] = re.sub(r"/+", "/", raw_path)
    return await call_next(request)

# Mount routes with both /api prefix and root / so any URL format works seamlessly
app.include_router(router, prefix="/api")
app.include_router(router, prefix="")

@app.get("/")
@app.get("/health")
async def root_health():
    return {
        "status": "healthy",
        "service": "ClearView Fraud & Compliance Intelligence API",
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
