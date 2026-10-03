"""keel.jobs — 后台作业管理(journey_run 异步化)

journey 在后台线程执行, 立即返回 jobId; manager 轮询 journey_status 获取结果。
内存 job 表(不持久化, 服务重启即清——可接受, 旅程可重跑)。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    id: str
    kind: str                              # "journey_run" | 其他后台作业
    state: str = "running"                 # running | done | failed
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    result: dict[str, Any] | None = None   # 完成时的返回值
    error: str | None = None

    def to_dict(self, include_result: bool = True) -> dict:
        d = {"jobId": self.id, "kind": self.kind, "state": self.state,
             "elapsed": round(time.time() - self.started_at, 1)}
        if self.finished_at:
            d["duration"] = round(self.finished_at - self.started_at, 1)
        if self.error:
            d["error"] = self.error
        if include_result and self.result is not None:
            d["result"] = self.result
        return d


class JobManager:
    """线程安全的内存作业表。"""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def submit(self, kind: str, fn: Callable[[], dict[str, Any]]) -> str:
        """提交后台作业, 返回 jobId。fn 在后台线程执行, 返回值存入 Job.result。"""
        self._counter += 1
        job_id = f"j_{uuid.uuid4().hex[:8]}"
        job = Job(id=job_id, kind=kind)
        with self._lock:
            self._jobs[job_id] = job

        def _run():
            try:
                job.result = fn()
                job.state = "done"
            except SystemExit as e:
                # CLI 的 sys.exit(1) → 视为失败但有结果
                job.state = "failed" if e.code else "done"
                job.error = f"exit code {e.code}"
            except Exception as e:
                job.state = "failed"
                job.error = f"{type(e).__name__}: {e}"
            finally:
                job.finished_at = time.time()

        threading.Thread(target=_run, daemon=True, name=f"keel-job-{job_id}").start()
        return job_id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def status(self, job_id: str, include_result: bool = True) -> dict | None:
        job = self.get(job_id)
        return job.to_dict(include_result) if job else None

    def list_active(self) -> list[dict]:
        with self._lock:
            return [j.to_dict(False) for j in self._jobs.values() if j.state == "running"]

    def cleanup(self, max_age: float = 3600) -> None:
        """清理超过 max_age 的已完成作业(防内存膨胀)。"""
        cutoff = time.time() - max_age
        with self._lock:
            stale = [k for k, j in self._jobs.items()
                     if j.state != "running" and j.started_at < cutoff]
            for k in stale:
                del self._jobs[k]


# 全局单例(MCP server 与 CLI 共用)
manager = JobManager()
