import asyncio

import pytest

from jcodemunch_mcp.index_jobs import IndexJobRegistry


@pytest.mark.asyncio
async def test_background_index_job_reports_progress_and_invalidates_after_completion():
    registry = IndexJobRegistry()
    started = asyncio.Event()
    release = asyncio.Event()
    invalidations: list[None] = []

    async def worker(progress):
        progress(1, 2, "Parsing")
        started.set()
        await release.wait()
        progress(2, 2, "Saving")
        return {"success": True, "repo": "local/example"}

    submitted = registry.start("index_folder", "/tmp/example", worker, lambda: invalidations.append(None))
    assert submitted["status"] == "queued"
    assert submitted["existing"] is False

    await started.wait()
    running = registry.get(submitted["job_id"])
    assert running["status"] == "running"
    assert running["progress"] == {"current": 1, "total": 2, "message": "Parsing"}
    assert invalidations == []

    release.set()
    for _ in range(20):
        completed = registry.get(submitted["job_id"])
        if completed["status"] == "completed":
            break
        await asyncio.sleep(0)
    assert completed["status"] == "completed"
    assert completed["result"] == {"success": True, "repo": "local/example"}
    assert invalidations == [None]


@pytest.mark.asyncio
async def test_background_index_failure_keeps_cache_valid():
    registry = IndexJobRegistry()
    invalidations: list[None] = []

    async def worker(_progress):
        return {"success": False, "error": "Folder not found"}

    submitted = registry.start("index_folder", "/missing", worker, lambda: invalidations.append(None))
    for _ in range(20):
        failed = registry.get(submitted["job_id"])
        if failed["status"] == "failed":
            break
        await asyncio.sleep(0)
    assert failed["status"] == "failed"
    assert failed["error"] == "Folder not found"
    assert invalidations == []
