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
from app.extract import ExtractionError, extract_pdf
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
    # Filenames whose extraction failed after retries. Non-empty even when
    # `extract == "done"`, since a partial failure (some files ok, some
    # not) still lets the pipeline proceed -- this is how that gets
    # surfaced instead of silently disappearing. Each such file also gets
    # a "review - extraction failed" placeholder row in the output
    # workbook (see run_job).
    failed_files: list[str] = field(default_factory=list)

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
            "failed_files": self.failed_files,
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


def _failed_file_placeholder_row(filename: str) -> dict:
    """A visible stand-in row for a file whose extraction failed after
    retries, so the failure shows up as a flagged row in the workbook
    instead of that file's transactions just being absent with no trace.
    Pre-filled with terminal-stage fields (verification/enrichment) since
    it never goes through verify_rows/enrich_rows -- there is no real
    extracted data for those stages to act on."""
    return {
        "row_id": f"{filename}::EXTRACTION_FAILED",
        "account_name": "",
        "account_number": "",
        "currency": "",
        "bank_reference": "",
        "customer_reference": None,
        "trn_type": None,
        "value_date": None,
        "credit_amount": None,
        "debit_amount": None,
        "balance": None,
        "post_date": None,
        "narrative": (
            f"REVIEW - extraction failed for source file '{filename}' after "
            "retries. This file's transactions are NOT included in this "
            "workbook. Re-upload the file or re-run the job."
        ),
        "source_pdf": filename,
        "page": 1,
        "screenshot_path": "",
        "extraction_confidence": 0.0,
        "verification_notes": "Extraction failed after retries; row was never verified.",
        "pulled_project_code": None,
        "pulled_sender_beneficiary": None,
        "enrichment_confidence": 0.0,
        "enrichment_notes": (
            f"Extraction failed for source file '{filename}' after retries; "
            "no transaction data could be read from this PDF. Enrichment skipped."
        ),
    }


async def run_job(job_id: str, pdf_paths: list[Path]) -> None:
    """Runs extract -> verify (per file, phase-aligned across files) ->
    enrich (once, over the combined table) -> build, updating the job's
    stage statuses as it goes. Never raises -- failures are recorded on
    the job itself so the frontend can show them.

    A single file's extraction failing after retries does NOT abort the
    batch and does NOT silently disappear: it's recorded on
    `job.failed_files` and a "review - extraction failed" placeholder row
    for that file is included in the output workbook, so the analyst sees
    it rather than getting a "done"-stamped workbook quietly missing an
    entire statement's transactions.
    """
    job = _jobs[job_id]
    image_dir = job.tmp_dir / "screenshots"

    try:
        job.extract = "processing"

        async def _extract_one(path: Path) -> tuple[list[dict], str | None]:
            try:
                rows = await asyncio.to_thread(extract_pdf, path, image_dir)
                return rows, None
            except ExtractionError:
                logger.error(
                    "extraction failed for %s; flagging as a failed file on the job "
                    "and adding a placeholder row instead of dropping it silently",
                    path.name,
                )
                return [], path.name

        extract_outcomes = await asyncio.gather(*(_extract_one(p) for p in pdf_paths))
        per_file_rows = [rows for rows, _ in extract_outcomes]
        failed_files = [name for _, name in extract_outcomes if name]
        job.failed_files = failed_files
        job.extract = "error" if len(failed_files) == len(pdf_paths) else "done"

        job.verify = "processing"
        verified_per_file = await asyncio.gather(
            *(asyncio.to_thread(verify_rows, rows) for rows in per_file_rows)
        )
        job.verify = "done"

        all_rows: list[dict] = []
        for file_rows in verified_per_file:
            all_rows.extend(file_rows)

        if not all_rows and not failed_files:
            job.enrich = "error"
            job.error = "No transaction rows found in the uploaded PDFs"
            return

        job.enrich = "processing"
        enriched_rows = await asyncio.to_thread(enrich_rows, all_rows) if all_rows else []
        enriched_rows.extend(_failed_file_placeholder_row(name) for name in failed_files)
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
