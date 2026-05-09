from fastapi import APIRouter

from .tasks import router as tasks_router
from .pipeline import router as pipeline_router

api_router = APIRouter()
api_router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
api_router.include_router(pipeline_router, prefix="/pipeline", tags=["pipeline"])
