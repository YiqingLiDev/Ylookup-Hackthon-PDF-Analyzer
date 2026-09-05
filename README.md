# Ylookup Hackathon PDF Analyzer

Initial full-stack scaffold with a FastAPI backend and React frontend.

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
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
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

## Docker Compose

```bash
docker compose up --build
```

