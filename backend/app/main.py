import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings

# Populated by the Docker build (see Dockerfile), which copies the built
# Vite output here so the API can serve the SPA from the same process/port.
_FRONTEND_DIST = Path(__file__).resolve().parents[1] / "static"

# INFO-level logs (Gemini call start/success/failure per stage) are the main
# way to see whether the AI pipeline is actually running -- without this,
# uvicorn's default logging config only surfaces WARNING+ from app loggers.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)

    masked_key = f"{settings.gemini_api_key[:6]}...{settings.gemini_api_key[-4:]}" if settings.gemini_api_key else "(not set)"
    logger.info("Gemini config -> model=%s api_key=%s", settings.gemini_model, masked_key)
    if not settings.gemini_api_key:
        logger.error(
            "GEMINI_API_KEY is not set -- every Gemini call will be skipped and rows will "
            "get confidence=0. Check backend/.env and restart the server."
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "No files uploaded"})

    app.include_router(api_router, prefix="/api")

    if _FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")

    return app


app = create_app()

