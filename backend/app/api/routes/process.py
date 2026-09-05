import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.jobs import create_job, get_job, list_jobs, run_job

router = APIRouter()


@router.post("/process", status_code=202)
async def process(
    background_tasks: BackgroundTasks, files: list[UploadFile] = File(...)
) -> JSONResponse:
    """Kicks off processing for one upload batch and returns immediately with
    a job_id -- the actual extract/verify/enrich/build pipeline runs in the
    background so the caller isn't blocked, and other batches can be
    submitted in the meantime. Poll GET /api/jobs (or /api/jobs/{job_id})
    for status, then GET /api/jobs/{job_id}/download once ready."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    for f in files:
        if f.filename and not f.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400, detail=f"Only PDF files are accepted: {f.filename}"
            )

    tmp_dir = Path(tempfile.mkdtemp(prefix="sourceline-"))
    pdf_dir = tmp_dir / "input"
    pdf_dir.mkdir()

    pdf_paths: list[Path] = []
    filenames: list[str] = []
    for f in files:
        dest = pdf_dir / f.filename
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        pdf_paths.append(dest)
        filenames.append(f.filename)

    job = create_job(filenames, tmp_dir)
    background_tasks.add_task(run_job, job.job_id, pdf_paths)

    return JSONResponse(status_code=202, content={"job_id": job.job_id})


@router.get("/jobs")
async def jobs() -> list[dict]:
    return [j.to_dict() for j in list_jobs()]


@router.get("/jobs/{job_id}")
async def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.get("/jobs/{job_id}/download")
async def download_job(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.ready or job.output_path is None or not job.output_path.exists():
        raise HTTPException(status_code=409, detail="File is not ready yet")

    return FileResponse(
        path=job.output_path,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        filename="sourceline-output.xlsx",
    )
