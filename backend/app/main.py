import asyncio
import logging
import sys
import httpx
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import delete

from app.database import init_db, AsyncSessionLocal
from app.routers import analyze, profiles
from app.config import settings

_logger = logging.getLogger("clearpath")
_logger.setLevel(logging.DEBUG)
if not _logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(levelname)s clearpath: %(message)s"))
    _logger.addHandler(_h)
_logger.propagate = False


async def _warmup_ollama() -> None:
    """Pin the writer model in VRAM before the first real request arrives.

    Sends a minimal 1-token request with keep_alive=15m so the model is
    already loaded when users hit the /analyze endpoint.  Fails silently if
    Ollama is not yet available at startup time.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": settings.gemma_local_model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                    "think": False,
                    "keep_alive": "15m",
                    "options": {"num_predict": 1},
                },
            )
            if r.is_success:
                _logger.info("Ollama warm-up OK: model pinned in VRAM for 15 min")
            else:
                _logger.warning(f"Ollama warm-up failed: HTTP {r.status_code}")
    except Exception as e:
        _logger.warning(f"Ollama warm-up skipped (Ollama not ready?): {e}")


async def _cleanup_cache_loop() -> None:
    """Delete expired AnalysisCache rows every 10 minutes.

    Runs as a background task for the lifetime of the process.
    Fails silently so it never crashes the application.
    """
    # Import here to avoid circular import at module level
    from app.models.analysis_cache import AnalysisCache

    while True:
        await asyncio.sleep(600)  # 10 minutes
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    delete(AnalysisCache).where(
                        AnalysisCache.expires_at < datetime.now(timezone.utc)
                    )
                )
                await db.commit()
                deleted = result.rowcount
                if deleted:
                    _logger.debug(f"Cache cleanup: removed {deleted} expired entries")
        except Exception as e:
            _logger.warning(f"Cache cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Warm up in the background — don't block application startup
    asyncio.create_task(_warmup_ollama())
    asyncio.create_task(_cleanup_cache_loop())
    yield


app = FastAPI(
    title="ClearPath API",
    description="Cognitive Accessibility Agent for Education — powered by Gemma 4",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze.router)
app.include_router(profiles.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "clearpath-api"}
