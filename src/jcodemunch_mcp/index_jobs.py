"""In-process lifecycle records for explicitly backgrounded index requests."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional


ProgressCallback = Callable[[int, int, str], None]
IndexWorker = Callable[[ProgressCallback], Awaitable[dict]]


@dataclass(slots=True)
class _IndexJob:
    job_id: str
    kind: str
    target: str
    key: str
    created_at_ms: int
    status: str = "queued"
    updated_at_ms: int = 0
    progress: Optional[dict] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    task: Optional[asyncio.Task] = field(default=None, repr=False)


class IndexJobRegistry:
    """Own indexing jobs without borrowing request-scoped MCP progress state."""

    def __init__(self, max_completed_jobs: int = 100) -> None:
        self._jobs: dict[str, _IndexJob] = {}
        self._active_by_key: dict[str, str] = {}
        self._lock = threading.RLock()
        self._max_completed_jobs = max_completed_jobs

    def start(
        self,
        kind: str,
        target: str,
        worker: IndexWorker,
        on_success: Callable[[], None],
    ) -> dict:
        key = f"{kind}:{target}"
        with self._lock:
            existing_id = self._active_by_key.get(key)
            if existing_id and (existing := self._jobs.get(existing_id)):
                return self._snapshot(existing, existing=True)

            now = self._now_ms()
            job = _IndexJob(
                job_id=uuid.uuid4().hex,
                kind=kind,
                target=target,
                key=key,
                created_at_ms=now,
                updated_at_ms=now,
            )
            self._jobs[job.job_id] = job
            self._active_by_key[key] = job.job_id
            job.task = asyncio.create_task(self._run(job, worker, on_success), name=f"index:{kind}:{job.job_id}")
            return self._snapshot(job, existing=False)

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            return self._snapshot(job) if job else None

    async def _run(self, job: _IndexJob, worker: IndexWorker, on_success: Callable[[], None]) -> None:
        self._update(job, status="running")
        try:
            result = await worker(lambda current, total, message: self._progress(job, current, total, message))
        except Exception as exc:
            self._update(job, status="failed", error=f"{type(exc).__name__}: {exc}")
            return

        if result.get("success") is False:
            self._update(job, status="failed", result=result, error=str(result.get("error", "Indexing failed")))
            return

        self._update(job, status="completed", result=result)
        try:
            on_success()
        except Exception:
            # Cache invalidation is an optimization. A completed index must not be
            # reported as failed merely because stale cache entries need expiry.
            pass

    def _progress(self, job: _IndexJob, current: int, total: int, message: str) -> None:
        with self._lock:
            if job.status not in {"queued", "running"}:
                return
            job.progress = {"current": current, "total": total, "message": message}
            job.updated_at_ms = self._now_ms()

    def _update(
        self,
        job: _IndexJob,
        *,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            job.status = status
            job.updated_at_ms = self._now_ms()
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            if status in {"completed", "failed"}:
                self._active_by_key.pop(job.key, None)
                self._prune_completed()

    def _prune_completed(self) -> None:
        completed = sorted(
            (job for job in self._jobs.values() if job.status in {"completed", "failed"}),
            key=lambda job: job.updated_at_ms,
        )
        for job in completed[: max(0, len(completed) - self._max_completed_jobs)]:
            self._jobs.pop(job.job_id, None)

    @staticmethod
    def _snapshot(job: _IndexJob, existing: Optional[bool] = None) -> dict:
        result = {
            "job_id": job.job_id,
            "kind": job.kind,
            "target": job.target,
            "status": job.status,
            "created_at_ms": job.created_at_ms,
            "updated_at_ms": job.updated_at_ms,
        }
        if job.progress is not None:
            result["progress"] = job.progress
        if job.result is not None:
            result["result"] = job.result
        if job.error is not None:
            result["error"] = job.error
        if existing is not None:
            result["existing"] = existing
        return result

    @staticmethod
    def _now_ms() -> int:
        return round(time.time() * 1000)
