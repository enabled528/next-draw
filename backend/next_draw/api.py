from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .jobs import JobManager
from .process import ProcessPipeline
from .service import PredictionService, ROOT


class PredictionRequest(BaseModel):
    game: Literal["ssq", "dlt", "qlc"]
    request_id: str = Field(min_length=8, max_length=128)


def create_app(data_dir=None, service=None, frontend_dir=None):
    isolated = service is None
    service = service or PredictionService(data_dir)
    root = data_dir or getattr(service, "data_dir", ROOT / ".data")
    manager = JobManager(root, ProcessPipeline(root) if isolated else service.run)

    @asynccontextmanager
    async def lifespan(app):
        yield
        manager.close()

    app = FastAPI(title="Next Draw", version="0.1.0", lifespan=lifespan)
    app.state.jobs = manager

    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "next-draw", "architecture": __import__("platform").machine()}

    @app.get("/api/games")
    def games():
        return service.games()

    @app.post("/api/predictions", status_code=202)
    def submit(request: PredictionRequest):
        try: return manager.submit(request.game, request.request_id)
        except OverflowError as exc: raise HTTPException(429, str(exc)) from exc
        except ValueError as exc: raise HTTPException(409, str(exc)) from exc

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        try: return manager.get(job_id)
        except (KeyError, ValueError): raise HTTPException(404, "任务不存在")

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        try: return manager.cancel(job_id)
        except (KeyError, ValueError): raise HTTPException(404, "任务不存在")

    frontend = Path(frontend_dir or ROOT / "frontend/dist/client")
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    else:
        @app.get("/")
        def frontend_missing():
            return JSONResponse({"detail": "前端尚未构建"}, status_code=503)
    return app


app = create_app()
