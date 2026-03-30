from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.health import router as health_router
from app.api.routes.twilio import router as twilio_router
from app.api.routes.webrtc import router as webrtc_router
from app.api.routes.websocket import router as websocket_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import init_db
from app.utils.helpers import ensure_directory


settings = get_settings()
configure_logging(settings.log_level, settings.app_env)
ensure_directory(settings.dashboard_path)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(
    "/dashboard",
    StaticFiles(directory=settings.dashboard_dir, html=True, check_dir=True),
    name="dashboard",
)

app.include_router(health_router)
app.include_router(twilio_router, prefix=settings.api_prefix)
app.include_router(webrtc_router, prefix=settings.api_prefix)
app.include_router(websocket_router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard/")
