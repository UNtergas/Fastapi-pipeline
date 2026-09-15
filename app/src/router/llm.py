# pyright: reportMissingTypeStubs=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
from ollama import Client

from router.setting import settings
from router.schema import Classification, Category
from router.errors import parse_classification

client = Client(host=settings.ollama_url)

_CATEGORIES = ", ".join(c.value for c in Category)
_SYSTEM = (
    "Classify the user's task into exactly one category.\n"
    f"Allowed categories: {_CATEGORIES}.\n"
    "Use 'other' only if none of the specific categories fit.\n"
    "Reply with JSON only, exactly this shape:\n"
    '{"category": "<one allowed category>", "confidence": <number 0..1>, '
    '"reason": "<short reason>"}'
)


def classify(task: str) -> Classification:
    response = client.chat(
        model=settings.ollama_model,
        messages=[
            {
                "role": "system",
                "content": _SYSTEM,
            },
            {
                "role": "user",
                "content": task,
            },
        ],
        format=Classification.model_json_schema(),
        think=False
    )

    # Fallback to pre-defined parse if ollama failed to apply model_json_schema
    return parse_classification(response.message.content)