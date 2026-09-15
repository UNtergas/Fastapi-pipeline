from ollama import Client

from router.setting import settings
from router.schema import Classification
from router.errors import parse_classification

client = Client(host=settings.ollama_url)

_SYSTEM = (
    "Classify the user's task into exactly one category. "
    "Use 'other' only if none of the specific categories fit. "
    "Set confidence to your certainty from 0 to 1. Decide from the task text alone."
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
        format="json",
    )

    return parse_classification(response.message.content)