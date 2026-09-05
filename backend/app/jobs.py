"""In-memory job tracking for the async (non-blocking) processing pipeline.

Each uploaded batch of PDFs becomes one job with three trackable stages --
extract, verify, enrich, matching the three Gemini API calls -- so the
frontend can show live per-stage status without the UI blocking on a
single long synchronous request. This is intentionally a plain in-memory
dict, not a database or persistent queue: jobs live only for the life of
the backend process, which is fine for this single-user MVP.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.build import build_workbook
from app.enrich import enrich_rows
from app.extract import extract_pdf
from app.verify import verify_rows

logger = logging.getLogger(__name__)

StageStatus = str  # "pending" | "processing" | "done" | "error"


@dataclass
class Job:
    job_id: str
    filenames: list[str]
    tmp_dir: Path
    created_at: float = field(default_factory=time.time)
    extract: StageStatus = "pending"
    verify: StageStatus = "pending"
    enrich: StageStatus = "pending"
    ready: bool = False
    error: str | None = None
    output_path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "filenames": self.filenames,
            "created_at": self.created_at,
            "extract": self.extract,
            "verify": self.verify,
            "enrich": self.enrich,
            "ready": self.ready,
            "error": self.error,
        }


_jobs: dict[str, Job] = {}


def create_job(filenames: list[str], tmp_dir: Path) -> Job:
    job = Job(job_id=str(uuid.uuid4()), filenames=filenames, tmp_dir=tmp_dir)
    _jobs[job.job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def list_jobs() -> list[Job]:
    return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)


async def run_job(job_id: str, pdf_paths: list[Path]) -> None:
    """Runs extract -> verify (per file, phase-aligned across files) ->
    enrich (once, over the combined table) -> build, updating the job's
    stage statuses as it goes. Never raises -- failures are recorded on
    the job itself so the frontend can show them."""
    job = _jobs[job_id]
    image_dir = job.tmp_dir / "screenshots"

    try:
        job.extract = "processing"
        per_file_rows = await asyncio.gather(
            *(asyncio.to_thread(extract_pdf, p, image_dir) for p in pdf_paths)
        )
        job.extract = "done"

        job.verify = "processing"
        verified_per_file = await asyncio.gather(
            *(asyncio.to_thread(verify_rows, rows) for rows in per_file_rows)
        )
        job.verify = "done"

        all_rows: list[dict] = []
        for file_rows in verified_per_file:
            all_rows.extend(file_rows)

        if not all_rows:
            job.enrich = "error"
            job.error = "No transaction rows found in the uploaded PDFs"
            return

        job.enrich = "processing"
        enriched_rows = await asyncio.to_thread(enrich_rows, all_rows)
        job.enrich = "done"

        output_path = job.tmp_dir / "sourceline-output.xlsx"
        await asyncio.to_thread(build_workbook, enriched_rows, output_path)
        job.output_path = output_path
        job.ready = True
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        job.error = str(exc)
        for stage_name in ("extract", "verify", "enrich"):
            if getattr(job, stage_name) == "processing":
                setattr(job, stage_name, "error")
