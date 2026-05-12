from fastapi import APIRouter

from .architecture import router as architecture_router
from .auth import router as auth_router
from .billing import router as billing_router
from .cost import router as cost_router
from .knowledge import router as knowledge_router
from .monitoring import dashboard_router, monitor_router
from .ontology_dashboard import router as ontology_dashboard_router
from .pipeline import router as pipeline_router
from .svg import router as svg_router
from .tasks import router as tasks_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
api_router.include_router(pipeline_router, prefix="/pipeline", tags=["pipeline"])
api_router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(cost_router, prefix="/cost", tags=["cost"])
api_router.include_router(billing_router, prefix="/billing", tags=["billing"])
api_router.include_router(svg_router, prefix="/svg", tags=["svg"])
api_router.include_router(
    architecture_router,
    prefix="/architecture",
    tags=["architecture"],
)
api_router.include_router(monitor_router)
api_router.include_router(dashboard_router)
api_router.include_router(
    ontology_dashboard_router,
    prefix="/ontology",
    tags=["ontology"],
)
