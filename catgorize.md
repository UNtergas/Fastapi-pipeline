# Plan 1 (detailed) — Strictly-Typed Categorization Contract

The categorizer isn't just "an LLM returns a label." It produces a **strictly-typed Pydantic
result** that becomes a formal API contract: Pydantic → OpenAPI → generated TypeScript types.
Any consumer — the frontend, an n8n workflow, an MCP agent, another service — reads the
classification with full type safety, from one source of truth.

Two guarantees this buys you:
1. **The LLM output is validated to an exact shape.** instructor forces the model's answer
   into your Pydantic model; anything off-shape is rejected and retried. Downstream code never
   sees a malformed classification.
2. **Consumers get the types for free.** The same models generate the OpenAPI spec, from which
   `openapi-typescript` produces TS types. The frontend imports them; a drift is a compile
   error, not a runtime surprise.

---

## Why strict typing here specifically

The classification result is the **hand-off point** between systems: the LLM produces it, and
the frontend renders it, n8n routes on it, an agent reasons over it. If its shape is loose,
every one of those consumers has to defensively parse and guess. If it's a strict schema:

- the **frontend** gets `category: "banking" | "credit_cards" | ...` as a real union, not
  `string`;
- **n8n** receives a predictable JSON body;
- **another service / MCP** can rely on the fields existing and being bounded;
- and the **contract is enforced at both ends** — the LLM can't emit an unknown category, and
  the frontend can't read a field that isn't there.

Loose typing at a hand-off point is where integration bugs breed. This locks it down once.

---

## Project setup (recap)

```bash
mkdir router && cd router
uv init --python 3.13 --no-workspace
rm -f main.py hello.py
mkdir src && touch src/__init__.py
uv add "fastapi[standard]" datasets instructor
uv add openai                     # or google-genai / anthropic
uv add --dev basedpyright         # static type checking (the tsc equivalent)
```

`pyproject.toml` — app mode + strict type checking:

```toml
[project]
name = "router"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = [
    "fastapi[standard]>=0.141.1",
    "datasets>=2.0.0",
    "instructor>=1.0.0",
]

[tool.uv]
package = false

[dependency-groups]
dev = ["basedpyright>=1.31.0"]

[tool.basedpyright]
typeCheckingMode = "strict"       # you want strict here — the contract is the product
pythonVersion = "3.13"
include = ["src"]
```

---

## The type layer — `src/schemas.py`

Every model is strict (`extra="forbid"`), every field is bounded or enumerated. This file
**is** the contract.

```python
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Category(str, Enum):
    """Closed set of categories. Becomes a TS string-union on the frontend."""
    banking = "banking"
    credit_cards = "credit_cards"
    travel = "travel"
    dining = "dining"
    calendar = "calendar"
    home = "home"
    other = "other"


class Classification(BaseModel):
    """The LLM's typed decision for a single task. This is the hand-off shape."""
    model_config = ConfigDict(extra="forbid")

    category: Category = Field(description="the single best category for the task")
    confidence: float = Field(ge=0.0, le=1.0, description="self-reported, 0..1 (see caveat)")
    reason: str = Field(min_length=1, description="short justification, citing task words")


class TaskResult(BaseModel):
    """One task, its classification, and (in eval mode) whether it matched ground truth."""
    model_config = ConfigDict(extra="forbid")

    task: str
    classification: Classification
    true_category: Category | None = None   # only present when evaluating against labels
    correct: bool | None = None


class CategoryStat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicted: int
    correct: int


class RunSummary(BaseModel):
    """Batch run over labeled data: the measurable contract for the test case."""
    model_config = ConfigDict(extra="forbid")

    total: int
    accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    per_category: dict[Category, CategoryStat]
    results: list[TaskResult]
```

> **Caveat on `confidence`:** an LLM's self-reported confidence is *not* calibrated — treat it
> as a rough signal (useful for flagging low-confidence tasks for review or tuning the "other"
> threshold), not a probability. It's in the schema because a typed, bounded field is better
> than a magic number floating in prose, not because you should trust it precisely.

---

## Ground truth — `src/categories.py`

Same mapping as the test case, importing `Category` from the contract so there's one enum.

```python
from src.schemas import Category

CATEGORY_INTENTS: dict[Category, set[str]] = {
    Category.banking:      {"transfer", "balance", "bill_balance", "pay_bill",
                            "account_blocked", "routing", "order_checks", "pin_change"},
    Category.credit_cards: {"card_declined", "credit_limit", "report_lost_card", "new_card",
                            "credit_score", "apr", "redeem_rewards", "damaged_card"},
    Category.travel:       {"book_flight", "book_hotel", "flight_status", "car_rental",
                            "travel_alert", "exchange_rate", "carry_on", "international_visa"},
    Category.dining:       {"restaurant_reservation", "restaurant_reviews", "recipe",
                            "meal_suggestion", "cook_time", "nutrition_info", "calories"},
    Category.calendar:     {"schedule_meeting", "calendar", "calendar_update", "reminder",
                            "alarm", "time", "date", "next_holiday"},
    Category.home:         {"smart_home", "todo_list", "todo_list_update", "shopping_list",
                            "shopping_list_update"},
}

_INTENT_TO_CATEGORY: dict[str, Category] = {
    intent: cat for cat, intents in CATEGORY_INTENTS.items() for intent in intents
}
MAPPED_INTENTS = set(_INTENT_TO_CATEGORY)


def true_category(intent: str) -> Category:
    return _INTENT_TO_CATEGORY.get(intent, Category.other)
```

---

## The classifier — `src/llm.py`

`instructor` validates the model's output against `Classification`. Because the model is
strict and `category` is the enum, an off-shape or unknown-category answer is rejected and
retried — the function's return type is a guarantee, not a hope.

```python
import instructor

from src.schemas import Classification

client = instructor.from_provider("openai/gpt-4o-mini")   # or google/gemini-... etc.

_SYSTEM = (
    "Classify the user's task into exactly one category. "
    "Use 'other' only if none of the specific categories fit. "
    "Set confidence to your certainty from 0 to 1. Decide from the task text alone."
)


def classify(task: str) -> Classification:
    return client.chat.completions.create(
        response_model=Classification,
        max_tokens=200,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": task},
        ],
    )
```

---

## Dataset loader — `src/data.py`

```python
from datasets import load_dataset

from src.categories import true_category
from src.schemas import Category

TEXT_COL = "text"      # ← set from: uv run python -c "from datasets import load_dataset; \
LABEL_COL = "label"    #   print(load_dataset('DeepPavlov/clinc150', split='test')[0])"


def load_tasks(n: int, include_other: bool = False) -> list[tuple[str, Category]]:
    ds = load_dataset("DeepPavlov/clinc150", split="test").shuffle(seed=42)
    out: list[tuple[str, Category]] = []
    for row in ds:
        label = row[LABEL_COL]
        intent = label if isinstance(label, str) else ds.features[LABEL_COL].names[label]
        cat = true_category(intent)
        if cat is Category.other and not include_other:
            continue
        out.append((row[TEXT_COL], cat))
        if len(out) >= n:
            break
    return out
```

---

## The API — `src/main.py`

Two endpoints, both returning strict typed models: `/classify` (single, what the frontend
calls live) and `/run` (batch eval against labels).

```python
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

from src.categories import Category
from src.data import load_tasks
from src.llm import classify
from src.schemas import CategoryStat, Classification, RunSummary, TaskResult


def unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name


app = FastAPI(title="router", generate_unique_id_function=unique_id)


class ClassifyBody(BaseModel):
    task: str


@app.post("/classify", response_model=Classification, tags=["classify"])
def classify_one(body: ClassifyBody) -> Classification:
    """Classify a single task. The frontend calls this; response is fully typed."""
    return classify(body.task)


@app.post("/run", response_model=RunSummary, tags=["classify"])
def run(n: int = 50, include_other: bool = False) -> RunSummary:
    """Batch-classify labeled tasks and score against ground truth."""
    tasks = load_tasks(n, include_other=include_other)
    results: list[TaskResult] = []
    correct = 0

    for text, truth in tasks:
        cls = classify(text)
        ok = cls.category is truth
        correct += ok
        results.append(
            TaskResult(task=text, classification=cls, true_category=truth, correct=ok)
        )

    per: dict[Category, CategoryStat] = {}
    for cat in Category:
        preds = [r for r in results if r.classification.category is cat]
        per[cat] = CategoryStat(
            predicted=len(preds), correct=sum(bool(r.correct) for r in preds)
        )

    return RunSummary(
        total=len(results),
        accuracy=round(correct / len(results), 3) if results else None,
        per_category=per,
        results=results,
    )


@app.get("/health", tags=["meta"])
def health() -> dict[str, bool]:
    return {"ok": True}
```

Create `src/openapi.py` (dumps the contract for the frontend):

```python
import json

from src.main import app

print(json.dumps(app.openapi()))
```

---

## Consume the contract from the frontend (or anywhere)

The whole point: the typed models become consumable types elsewhere, generated — never
hand-written.

```bash
# in the frontend project
npx openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.d.ts
```

The frontend now has, generated from your Pydantic:

```ts
// schema.d.ts (generated) — Category is a real union, Classification is a real shape
type Category = "banking" | "credit_cards" | "travel" | "dining"
              | "calendar" | "home" | "other";

interface Classification {
  category: Category;
  confidence: number;
  reason: string;
}
```

A component rendering a classification is fully typed:

```tsx
function CategoryBadge({ c }: { c: Classification }) {
  // c.category is typed to the union — a typo like "bankng" is a compile error
  return <span data-cat={c.category}>{c.category} ({Math.round(c.confidence * 100)}%)</span>;
}
```

Change the Pydantic model → regenerate → the frontend type-errors on anything that drifted.
n8n, MCP, and any other consumer read the same `/openapi.json`. **One contract, many
consumers, all typed.**

---

## Static type checking (the backend half of the guarantee)

```bash
uv run basedpyright            # or: uv run basedpyright --watch in a second terminal
```

Strict mode here catches type errors in your own code before it runs — the `tsc` for the
Python side. Together with Pydantic (runtime validation at the boundary) and the generated TS
types (frontend), the classification shape is guaranteed end to end: enforced when produced,
persisted, transported, and consumed.

---

## What this plan delivers

- A **strict Pydantic contract** for classification (`Classification`, `TaskResult`,
  `RunSummary`) — the single source of truth for the shape.
- LLM output **validated to that contract** by instructor — no malformed classifications
  downstream.
- The contract **published as OpenAPI** and **generated into TS types** — the frontend and any
  other consumer read it type-safe, with drift caught at compile time.
- **Static type checking** on the Python side so the code that produces the contract is itself
  type-correct.

This is the foundation Plan 2 builds on: it takes these typed results, dispatches each to an
n8n action, and **persists them in Postgres for caching** — storing and reading back the exact
same typed shape.