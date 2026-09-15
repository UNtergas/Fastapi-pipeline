
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

from router.categories import Category
from router.data import load_tasks
from router.llm import classify
from router.schema import CategoryStat, Classification, RunSummary, TaskResult


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
    """
        Batch-classify labeled tasks and score against ground truth.
        We using this endpoint to try to evaluate if the system prompt 
        is efficient or not
    """
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