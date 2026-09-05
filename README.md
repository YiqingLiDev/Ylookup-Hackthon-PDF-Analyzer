# Sourceline

AI-assisted bank statement matching: FastAPI backend + React frontend. Upload PDF
bank statements, Gemini extracts/verifies/enriches each transaction, and you
download an Excel workbook with a confidence score and source-page screenshot
per row for human review.

## Project Layout

```text
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── schemas/
│   │   └── main.py
│   └── tests/
└── frontend/
    └── src/
```

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # set GEMINI_API_KEY
uvicorn app.main:app --reload --port 8000
```

The API will run at `http://localhost:8000`.

## Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

The React app will run at `http://localhost:5173`.
