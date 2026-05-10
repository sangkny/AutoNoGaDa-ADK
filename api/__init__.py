from fastapi import APIRouter

from .architecture import router as architecture_router
from .auth import router as auth_router
from .monitoring import dashboard_router, monitor_router
from .pipeline import router as pipeline_router
from .svg import router as svg_router
from .tasks import router as tasks_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
api_router.include_router(pipeline_router, prefix="/pipeline", tags=["pipeline"])
api_router.include_router(svg_router, prefix="/svg", tags=["svg"])
api_router.include_router(
    architecture_router,
    prefix="/architecture",
    tags=["architecture"],
)
api_router.include_router(monitor_router)
api_router.include_router(dashboard_router)
