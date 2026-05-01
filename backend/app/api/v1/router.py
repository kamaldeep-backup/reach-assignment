from fastapi import APIRouter

from app.api.v1.routes.api_keys import router as api_keys_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.job_stream import router as job_stream_router
from app.api.v1.routes.jobs import router as jobs_router

api_router = APIRouter()
api_router.include_router(api_keys_router)
api_router.include_router(auth_router)
api_router.include_router(health_router)
api_router.include_router(job_stream_router)
api_router.include_router(jobs_router)
