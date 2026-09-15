# Plan 2 (detailed) — n8n Actions + Postgres Caching

Plan 1 produces a strictly-typed `Classification`. Plan 2 makes each category **do real work**
via n8n, and **persists every result in a local Postgres database** so a repeated task skips
both the LLM call *and* the n8n call. The cache stores and reads back the exact typed shape
from Plan 1.

```
task ──► [cache lookup by task hash] ──hit──► return stored result (source: "cache")
                    │ miss
                    ▼
             classify (LLM) ──► Classification ──► dispatch → n8n workflow (per category)
                    │                                              │
                    └────────────── store result in Postgres ◄─────┘  (source: "live")
```

**Why persist + cache:**
- **Quota** — the sponsor LLM key is limited; a cache hit costs zero LLM calls. Re-running the
  demo doesn't burn quota.
- **Determinism** — a cached result is byte-identical every time. Pre-warm the cache and the
  live demo is fast and reproducible (with provenance shown — see below — so it stays honest).
- **Speed** — cache hits skip a network round-trip to the LLM and to n8n.
- **A record** — every classification + action is stored, which is a debugging tool and, for a
  judged repo, evidence of a real pipeline with history.

---

## 1. Local Postgres + n8n via Docker

`docker-compose.yml` — a local Postgres for the app's cache, plus n8n for the actions:

```yaml
services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_PASSWORD: dev
      POSTGRES_DB: router
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 2s
      timeout: 3s
      retries: 20

  n8n:
    image: n8nio/n8n
    ports:
      - "5678:5678"
    environment:
      - N8N_SECURE_COOKIE=false
      - N8N_RUNNERS_ENABLED=true
    volumes:
      - n8n_data:/home/node/.n8n
      - ./fixtures:/data           # workflows read/write files here

volumes:
  pgdata:
  n8n_data:
```

```bash
mkdir -p fixtures/home fixtures/events      # + drop transactions.csv in fixtures/
docker compose up -d
```

FastAPI runs on the **host** and reaches both by localhost: Postgres at `localhost:5432`, n8n
at `localhost:5678`. (If you later move FastAPI into this compose file, switch those to the
service names `db:5432` and `n8n:5678`.)

---

## 2. Dependencies and settings

Add the ORM and Postgres driver to the Plan 1 project:

```bash
uv add sqlmodel "psycopg[binary]"
```

`src/settings.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://postgres:dev@localhost:5432/router"
    N8N_BASE_URL: str = "http://localhost:5678"
    PROMPT_VERSION: str = "v1"     # bump to invalidate the cache when prompt/categories change
```

`PROMPT_VERSION` is part of the cache key — change your prompt or category definitions, bump
this, and old cached results stop matching (so you don't serve stale classifications).

---

## 3. The ORM model — `src/models_db.py`

One table. The typed `Classification` and the n8n action are stored as JSON columns; reading
them back reconstructs the exact Plan 1 shapes.

```python
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class CachedResult(SQLModel, table=True):
    __tablename__ = "cached_results"

    id: int | None = Field(default=None, primary_key=True)
    task_hash: str = Field(index=True, unique=True)     # sha256(prompt_version + task)
    task: str
    category: str                                        # denormalised for easy querying
    classification: dict[str, Any] = Field(sa_column=Column(JSON))   # the Classification
    action_result: dict[str, Any] = Field(sa_column=Column(JSON))    # the n8n output
    source: str = "live"                                 # how it was originally produced
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

> On Postgres you can use `JSONB` instead of `JSON` for indexable JSON; `JSON` is fine and
> portable for a cache. The `unique` index on `task_hash` is what makes the lookup O(1) and
> prevents duplicate rows.

`src/db.py`:

```python
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine

from src.settings import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
```

---

## 4. The cache layer — `src/cache.py`

Hash the (normalised) task with the prompt version; look up; store. Storing uses
`model_dump(mode="json")` so the enum serialises to a string and the column is JSON-safe;
reading uses `model_validate` to reconstruct the typed `Classification`.

```python
import hashlib
from typing import Any

from sqlmodel import Session, select

from src.models_db import CachedResult
from src.schemas import Classification
from src.settings import settings


def task_key(task: str) -> str:
    norm = task.strip().lower()
    return hashlib.sha256(f"{settings.PROMPT_VERSION}:{norm}".encode()).hexdigest()


def get_cached(session: Session, key: str) -> CachedResult | None:
    return session.exec(
        select(CachedResult).where(CachedResult.task_hash == key)
    ).first()


def store(
    session: Session,
    key: str,
    task: str,
    classification: Classification,
    action: dict[str, Any],
) -> CachedResult:
    row = CachedResult(
        task_hash=key,
        task=task,
        category=classification.category.value,
        classification=classification.model_dump(mode="json"),   # enum → string, JSON-safe
        action_result=action,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
```

---

## 5. n8n dispatch — `src/tools.py`

Each category triggers its n8n webhook (build the workflows per the n8n guide: banking reads a
CSV, home appends a list, calendar writes an event, travel calls an API). Every workflow must
be **Active** in n8n or you get 404s.

```python
import httpx

from src.schemas import Category
from src.settings import settings


def dispatch(category: Category, task: str) -> dict:
    """POST the task to the n8n workflow registered for this category."""
    url = f"{settings.N8N_BASE_URL}/webhook/{category.value}"
    try:
        r = httpx.post(url, json={"task": task}, timeout=30)
        if r.status_code == 404:
            return {"status": "no_workflow"}
        r.raise_for_status()
        return {"status": "ok", "result": r.json()}
    except httpx.RequestError as e:
        return {"status": "error", "detail": str(e)}
```

---

## 6. The response contract (typed, with provenance)

Add to `src/schemas.py` — the pipeline's output is also strictly typed, carrying **`source`**
so every result declares whether it came from cache or a live call (the honesty/provenance
signal).

```python
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from src.schemas import Category, Classification   # already defined in Plan 1


class ProcessedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str
    classification: Classification
    action: dict[str, Any]
    source: Literal["cache", "live"]


class ProcessSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: int
    cache_hits: int
    live_calls: int
    results: list[ProcessedTask]


class CachedResultPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str
    category: Category
    classification: Classification
    action_result: dict[str, Any]
    source: str
    created_at: str
```

---

## 7. The pipeline — `src/main.py`

`/process` (single task, cached) is what a frontend calls; `/run` batch-processes labeled data;
`/history` reads the stored cache. Tables are created on startup.

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel
from sqlmodel import select

from src.cache import get_cached, store, task_key
from src.data import load_tasks
from src.db import SessionDep, init_db
from src.llm import classify
from src.models_db import CachedResult
from src.schemas import (
    CachedResultPublic,
    Classification,
    ProcessedTask,
    ProcessSummary,
)
from src.tools import dispatch


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="router", lifespan=lifespan)


class ProcessBody(BaseModel):
    task: str


def _process(session, task: str) -> ProcessedTask:
    key = task_key(task)
    cached = get_cached(session, key)
    if cached is not None:
        return ProcessedTask(
            task=cached.task,
            classification=Classification.model_validate(cached.classification),
            action=cached.action_result,
            source="cache",
        )
    cls = classify(task)                    # LLM call  (skipped on cache hit)
    action = dispatch(cls.category, task)   # n8n call  (skipped on cache hit)
    store(session, key, task, cls, action)
    return ProcessedTask(task=task, classification=cls, action=action, source="live")


@app.post("/process", response_model=ProcessedTask, tags=["pipeline"])
def process_one(body: ProcessBody, s: SessionDep) -> ProcessedTask:
    return _process(s, body.task)


@app.post("/run", response_model=ProcessSummary, tags=["pipeline"])
def run(s: SessionDep, n: int = 20) -> ProcessSummary:
    results = [_process(s, text) for text, _truth in load_tasks(n)]
    hits = sum(r.source == "cache" for r in results)
    return ProcessSummary(
        total=len(results),
        cache_hits=hits,
        live_calls=len(results) - hits,
        results=results,
    )


@app.get("/history", response_model=list[CachedResultPublic], tags=["pipeline"])
def history(s: SessionDep, limit: int = 50) -> list[CachedResultPublic]:
    rows = s.exec(
        select(CachedResult).order_by(CachedResult.created_at.desc()).limit(limit)
    ).all()
    return [
        CachedResultPublic(
            task=r.task,
            category=Classification.model_validate(r.classification).category,
            classification=Classification.model_validate(r.classification),
            action_result=r.action_result,
            source=r.source,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@app.get("/health", tags=["meta"])
def health() -> dict[str, bool]:
    return {"ok": True}
```

---

## 8. Run it and what to expect

Bring up Postgres + n8n, activate the workflows, then start FastAPI:

```bash
docker compose up -d                 # db + n8n
export OPENAI_API_KEY=sk-...          # your test provider
uv run fastapi dev src/main.py
```

**First run — everything is live, cache fills:**

```bash
curl -X POST "http://localhost:8000/run?n=20"
# → {"total": 20, "cache_hits": 0, "live_calls": 20, "results": [...]}
```

20 LLM calls + 20 n8n calls, all stored.

**Second run — same tasks (seeded), all cache hits:**

```bash
curl -X POST "http://localhost:8000/run?n=20"
# → {"total": 20, "cache_hits": 20, "live_calls": 0, "results": [...]}
```

Zero LLM calls, zero n8n calls, near-instant — every result served from Postgres, each marked
`"source": "cache"`. That's the caching working: **quota preserved, deterministic, fast.**

**Inspect the stored record:**

```bash
curl "http://localhost:8000/history?limit=5"
# typed rows: task, category, the full Classification, the n8n action_result, source, timestamp
```

**Bump the prompt version → cache invalidates:**

```bash
# set PROMPT_VERSION=v2 in .env, restart
curl -X POST "http://localhost:8000/run?n=20"
# → live_calls: 20 again — new keys, old cache ignored (no stale classifications served)
```

### For the demo

Pre-warm the cache before you present (run `/run` once on your prepared tasks). On stage the
pipeline hits cache: fast, free, identical every time — and because each result carries
`source: "cache"`, you can show the judges it's cached rather than pretending it's live. Honest
and reliable.

---

## What this plan delivers

- **Real actions** — each category triggers its n8n workflow (the automation layer).
- **Local Postgres via Docker** — one compose file brings up the DB and n8n; no external
  dependency, data survives restarts.
- **An ORM cache** (SQLModel) that stores every classification + action and, on a repeat task,
  returns the stored result — **skipping both the LLM and n8n calls**.
- **Typed end to end** — the cache stores and reconstructs the exact Plan 1 `Classification`;
  the pipeline's `ProcessedTask` / `ProcessSummary` are strict Pydantic, so the frontend
  consumes the results (with provenance) type-safe, same as Plan 1.

Together: Plan 1 gives a guaranteed classification shape; Plan 2 executes on it and remembers
it. Swap the toy n8n actions and the CLINC dataset for the challenge's real ones — the typing,
caching, and wiring don't change.

---

## Gotchas

| Symptom | Cause | Fix |
|---|---|---|
| `connection refused` on startup | Postgres not up yet | `docker compose up -d` and wait for `db` healthy before starting FastAPI |
| Every run is `live`, never cache | Task text varies, or `task_key` not applied | Normalise in `task_key` (done); confirm same tasks (seeded loader) |
| Stale classifications after a prompt change | Cache not invalidated | Bump `PROMPT_VERSION` |
| `n8n` webhook 404 | Workflow not Active | Activate each workflow; FastAPI uses `/webhook/{category}` |
| `ModuleNotFoundError: psycopg2` | Bare `postgresql://` | Use `postgresql+psycopg://` (v3) in `DATABASE_URL` |
| JSON column errors on insert | Passing a Pydantic object, not a dict | Store `classification.model_dump(mode="json")` (done) |
| Duplicate-key error on store | Two tasks hash equal and race | Expected for identical tasks; check cache before storing (done) |