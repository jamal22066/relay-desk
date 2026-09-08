import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.auth_api import router as auth_router
from app.settings_api import router as settings_router
from app.config import settings
from app.headers import SecurityHeaders

_docs = None if settings.is_production else "/docs"

app = FastAPI(
    title="Relay desk",
    version="0.1.0",
    docs_url=_docs,
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(SecurityHeaders)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(router)


@app.get("/healthz")
def healthz():
    return {"ok": True}


_static = Path(__file__).resolve().parent.parent / "static"

if _static.is_dir():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Serve built files; anything unmatched falls through to the SPA."""
        candidate = _static / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_static / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")
