from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.auth_api import router as auth_router
from app.config import settings

app = FastAPI(title="Relay desk", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(router)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")
