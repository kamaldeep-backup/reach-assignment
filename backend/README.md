# Reach Backend

Minimal FastAPI backend scaffold.

## Setup

```bash
uv venv
source .venv/bin/activate
uv sync --dev
```

## Run locally

```bash
uv run uvicorn app.main:app --reload
```

Or, with the virtualenv activated:

```bash
uvicorn app.main:app --reload
```

## Health check

```bash
curl http://127.0.0.1:8000/api/v1/health
```

## Test

```bash
uv run pytest
```
