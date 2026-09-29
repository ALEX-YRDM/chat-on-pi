from contextlib import asynccontextmanager
import asyncio
from starlette.concurrency import run_in_threadpool
import logging
import os
from pathlib import Path
from .runtime import Runtime
from .status import StatusHub
from .security import LocalAPIMiddleware
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from .config import ConfigStore, ROOT
from .database import Database
from .errors import ServiceError
from .logging_setup import setup_logging
from .routes import health, chat, conversations, settings, audio, debug, pages, websocket


def create_app(config_path: Path | None = None, root: Path = ROOT) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        config = ConfigStore(config_path or Path(os.environ.get("LOCALCHAT_CONFIG", root / "config.yaml")))
        setup_logging(root, config.active.app.debug)
        logging.getLogger("localchat").info("LocalChat Voice Assistant")
        db = Database(root / "data/localchat.db")
        db.initialize()
        application.state.runtime = Runtime(config, db, root)
        application.state.runtime.hub = StatusHub()
        await run_in_threadpool(application.state.runtime.piper.initialize)
        report = await run_in_threadpool(health.health_report, application.state.runtime)
        logger = logging.getLogger("localchat")
        logger.info("Ollama %s", "reachable" if report["services"]["ollama"] else "unavailable; see /debug")
        logger.info("Server configured at %s:%s", config.active.app.host, config.active.app.port)
        async def monitor():
            while True:
                await asyncio.sleep(0.25)
                await run_in_threadpool(application.state.runtime.pipeline.check_recording)
        task = asyncio.create_task(monitor())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            application.state.runtime.close()

    application = FastAPI(title="LocalChat Voice Assistant", lifespan=lifespan)

    @application.exception_handler(ServiceError)
    async def service_error(_request: Request, exc: ServiceError):
        logging.getLogger("localchat").error("Service failure: %s", exc, exc_info=exc)
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc), "result": getattr(exc, "result", None)})

    @application.exception_handler(SQLAlchemyError)
    async def database_error(_request: Request, exc: SQLAlchemyError):
        logging.getLogger("localchat").error("Database operation failed", exc_info=exc)
        return JSONResponse(status_code=503, content={"detail": "数据库操作失败，请查看日志"})

    for module in (health, chat, conversations, settings, audio, debug, pages, websocket):
        application.include_router(module.router)
    @application.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception):
        logging.getLogger("localchat").error("Unhandled request failure", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "服务处理失败，请查看 logs/app.log"})

    application.add_middleware(LocalAPIMiddleware)
    application.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    return application


app = create_app()
