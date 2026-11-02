from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from hashlib import sha256
from pathlib import Path
from threading import RLock
import time
from uuid import uuid4, UUID

from .history import atomic_json, now
from .rules import GAMES


class Cancelled(Exception):
    pass


class JobManager:
    def __init__(self, root, pipeline, limit=4, timeout_seconds=600):
        self.root = Path(root); self.pipeline = pipeline; self.limit = limit; self.timeout_seconds = timeout_seconds
        self.lock = RLock(); self.jobs = {}; self.cancelled = set()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="next-draw")

    def _path(self, job_id):
        UUID(job_id)
        return self.root / "jobs" / f"{job_id}.json"

    def get(self, job_id):
        with self.lock:
            if job_id in self.jobs: return deepcopy(self.jobs[job_id])
            path = self._path(job_id)
            if path.exists():
                job = json.loads(path.read_text())
                if job["status"] not in ["complete", "failed", "cancelled"]:
                    job["status"] = "failed"; job["error"] = "服务已重启，请重新运行"; atomic_json(path, job)
                return job
            raise KeyError(job_id)

    def _emit(self, job_id, stage, message):
        with self.lock:
            job = self.jobs[job_id]
            job["events"].append({"sequence": len(job["events"]), "stage": stage, "message": message, "time": now()})
            job["stage"] = stage; job["message"] = message; job["updated_at"] = now()
            atomic_json(self._path(job_id), job)

    def submit(self, game, request_id):
        if game not in GAMES: raise ValueError("不支持的彩种")
        with self.lock:
            request_path = self.root / "requests" / f"{sha256(request_id.encode()).hexdigest()}.json"
            if request_path.exists():
                previous = json.loads(request_path.read_text())
                if previous["game"] != game: raise ValueError("同一请求标识不能更改彩种")
                return self.get(previous["id"])
            if sum(j["status"] in ["queued", "running", "cancelling"] for j in self.jobs.values()) >= self.limit:
                raise OverflowError("任务队列已满，请稍后重试")
            job_id = str(uuid4())
            self.jobs[job_id] = {"id": job_id, "game": game, "status": "queued", "events": [], "result": None,
                                 "created_at": now(), "updated_at": now(), "error": None}
            self._emit(job_id, "queued", "正在准备本次预测")
            atomic_json(request_path, {"id": job_id, "game": game})
            self.pool.submit(self._run, job_id)
            return deepcopy(self.jobs[job_id])

    def _run(self, job_id):
        started = time.monotonic()
        def check():
            if job_id in self.cancelled: raise Cancelled()
            if time.monotonic() - started > self.timeout_seconds: raise TimeoutError("任务超时，请重新尝试")
        def progress(stage, message):
            check()
            self._emit(job_id, stage, message)
        try:
            if job_id in self.cancelled: raise Cancelled()
            with self.lock: self.jobs[job_id]["status"] = "running"
            result = self.pipeline(self.jobs[job_id]["game"], progress, check)
            if job_id in self.cancelled: raise Cancelled()
            if time.monotonic() - started > self.timeout_seconds: raise TimeoutError("任务超时，请重新尝试")
            with self.lock:
                self.jobs[job_id]["status"] = "complete"
                self.jobs[job_id]["result"] = result
                self.jobs[job_id]["elapsed_seconds"] = round(time.monotonic() - started, 3)
                self._emit(job_id, "complete", "本次号码已生成")
        except Cancelled:
            with self.lock:
                self.jobs[job_id]["status"] = "cancelled"; self._emit(job_id, "cancelled", "本次运行已取消")
        except Exception as exc:
            with self.lock:
                self.jobs[job_id]["status"] = "failed"
                self.jobs[job_id]["error"] = str(exc)[:400]
                self._emit(job_id, "failed", "运行未完成，请重试")

    def cancel(self, job_id):
        with self.lock:
            job = self.get(job_id)
            if job["status"] not in ["complete", "failed", "cancelled"]:
                self.cancelled.add(job_id); self.jobs[job_id]["status"] = "cancelling"
                self._emit(job_id, "cancelling", "正在取消，当前步骤结束后停止")
            return self.get(job_id)

    def close(self):
        with self.lock:
            self.cancelled.update(j["id"] for j in self.jobs.values() if j["status"] in ["running", "queued", "cancelling"])
        self.pool.shutdown(wait=True)
        close = getattr(self.pipeline, "close", None)
        if close: close()
