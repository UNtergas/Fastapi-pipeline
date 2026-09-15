from enum import Enum
from pydantic import BaseModel, ConfigDict, Field

class Category(str,Enum):   
    banking = "banking"
    credit_cards = "credit_cards"
    travel = "travel"
    dining = "dining"
    calendar = "calendar"
    home = "home"
    other = "other"


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category = Field(description="the best category for the current task")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, description="short justification for the category")

class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str
    classification: Classification
    true_category: Category | None = None 
    correct: bool | None = None 


class CategoryStat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicted: int
    correct: int


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    per_category: dict[Category, CategoryStat]
    results: list[TaskResult]

