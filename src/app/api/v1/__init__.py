from fastapi import APIRouter
from .health import router as health_router
from .chat import router as chat_router
from .help import router as help_router

router = APIRouter(prefix="/v1")
router.include_router(health_router)
router.include_router(chat_router)
router.include_router(help_router)