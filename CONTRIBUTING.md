# Developing SourceLine

See the [root README](README.md) for the product pitch and pipeline overview.
This doc covers running it locally, project layout, and known limitations.

## Project layout

```text
.
├── backend/
│   ├── app/
│   │   ├── api/routes/       # process.py (upload/job/download), health.py
│   │   ├── core/config.py    # env-driven settings (Gemini key/model, CORS)
│   │   ├── reference/        # join_kit.py (master-data loader + join mirror)
│   │   │                     # + Staging_Sheet_Join_Kit.xlsx (reference workbook)
│   │   ├── ai.py             # shared Gemini client + retry helper
│   │   ├── extract.py        # Stage 1
│   │   ├── verify.py         # Stage 2
│   │   ├── enrich.py         # Stage 3
│   │   ├── build.py          # Stage 4 (writes the output .xlsx)
│   │   └── jobs.py           # in-memory job tracking + pipeline orchestration
│   ├── sample_data/          # sample statements + reference workbook for local testing
│   └── tests/
└── frontend/
    └── src/                  # single-page upload + job-status UI (React + Vite)
```

No database, no auth — jobs live in memory for the life of the backend process.
This is intentional for the hackathon scope (see "Known limitations").

## Running it locally

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set GEMINI_API_KEY, optionally GEMINI_MODEL
uvicorn app.main:app --reload --port 8000
```

The API runs at `http://localhost:8000`. Health check: `GET /api/health`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

The app runs at `http://localhost:5173`. Upload one or more PDFs, watch the
per-stage status, download the workbook once a row shows "Ready".

### API summary

| Method | Path                        | Purpose                                  |
|--------|-----------------------------|-------------------------------------------|
| POST   | `/api/process`               | Upload PDFs, kicks off a background job   |
| GET    | `/api/jobs`                  | List all jobs + their stage statuses      |
| GET    | `/api/jobs/{job_id}`         | Status of one job                         |
| GET    | `/api/jobs/{job_id}/download`| Download the finished workbook            |
| GET    | `/api/health`                | Liveness check                            |

## Known limitations (by design, for hackathon scope)

- **No auth, no database, no rate limiting.** Fine for a local demo; do not
  deploy this as-is anywhere reachable by untrusted users.
- **No cleanup of uploaded files/screenshots/output workbooks.** Each batch
  writes to a fresh temp directory that is never deleted — disk usage grows with
  every run.
- **The formula join is intentionally simple substring/lookup matching** (see
  `app/reference/join_kit.py` and the Enrich prompt in `app/enrich.py` for the
  specific documented weak spots — e.g. name-variant misses, "Related Party" vs.
  "Investment Transfer" ambiguity, an unverified "Cash Leg Transtype" pattern).
  These are surfaced via `enrichment_confidence` and `enrichment_notes` rather
  than silently hidden.
- **Gemini calls retry up to 2 times with no backoff.** A sustained rate limit
  or outage will show up as failed rows/files (flagged, not silently dropped),
  not as a hang.

## Data note

`backend/sample_data/statements/` is for local testing only and is
git-ignored — the sample PDFs contain realistic account numbers, IBANs, and
balances and are intentionally not committed. Drop your own test statements in
there locally; they won't be tracked.
