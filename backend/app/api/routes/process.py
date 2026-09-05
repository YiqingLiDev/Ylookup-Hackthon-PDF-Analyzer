import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from app.build import build_workbook
from app.extract import extract_pdfs
from app.resolve import resolve_rows

router = APIRouter()


@router.post("/process")
async def process(files: list[UploadFile] = File(...)) -> FileResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    for f in files:
        if f.filename and not f.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400, detail=f"Only PDF files are accepted: {f.filename}"
            )

    tmp_dir = Path(tempfile.mkdtemp(prefix="sourceline-"))
    try:
        pdf_dir = tmp_dir / "input"
        pdf_dir.mkdir()
        pdf_paths = []
        for f in files:
            dest = pdf_dir / f.filename
            with dest.open("wb") as out:
                shutil.copyfileobj(f.file, out)
            pdf_paths.append(dest)

        try:
            rows = extract_pdfs(pdf_paths, tmp_dir / "screenshots")
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to extract PDFs: {exc}") from exc

        if not rows:
            raise HTTPException(
                status_code=422, detail="No transaction rows found in the uploaded PDFs"
            )

        resolved_rows = resolve_rows(rows)

        output_path = tmp_dir / "sourceline-output.xlsx"
        build_workbook(resolved_rows, output_path)

        return FileResponse(
            path=output_path,
            media_type=(
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            ),
            filename="sourceline-output.xlsx",
            background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True),
        )
    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return JSONResponse(status_code=500, content={"error": str(exc)})
