from fastapi import APIRouter, Depends
from ..dependencies import runtime
from ..services.health_service import health_report

router = APIRouter(prefix="/api")


@router.get("/health")
def health(rt=Depends(runtime)):
    return health_report(rt)


@router.get("/status")
def status(rt=Depends(runtime)):
    return rt.pipeline.snapshot()
