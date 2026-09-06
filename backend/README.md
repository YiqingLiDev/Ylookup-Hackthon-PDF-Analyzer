# Backend

FastAPI service for AnalystAI. See the [root README](../README.md) for the full
pipeline overview and setup instructions.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

## Useful commands

```bash
pytest
ruff check .
```
