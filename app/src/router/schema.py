from enum import Enum
from pydantic import BaseModel, ConfigDict, Field

class Category(str,Enum):   
    """Defined categories, which will become a TS string union for consumer"""
    banking = "banking"
    credit_cards = "credit_cards"
    travel = "travel"
    dining = "dining"
    calendar = "calendar"
    home = "home"
    other = "other"


class Classification(BaseModel):
    """The LLM decision for categorizing"""
    model_config = ConfigDict(extra="forbid")

    category: Category = Field(description="the best category for the current task")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=1, description="short justification for the category")

class TaskResult(BaseModel):
    