"""
AutoNoGaDa ADK — FastAPI 엔트리

shared-libraries Orchestrator(PIPELINE) + OntologyValidator(SOFTWARE)
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from api import api_router
from config import get_settings
from database import create_tables

log = logging.getLogger("main")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("%s v%s 시작", settings.service_name, settings.version)
    await create_tables()
    yield
    log.info("%s 종료", settings.service_name)


app = FastAPI(
    title="AutoNoGaDa ADK",
    description="코드 자동화 — SOFTWARE Ontology + Agent PIPELINE",
    version=settings.version,
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api/v1")

from api.health import router as health_router  # noqa: E402

app.include_router(health_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
