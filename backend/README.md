# Backend

FastAPI service for the Ylookup PDF Analyzer.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

## Useful Commands

```bash
pytest
ruff check .
```

