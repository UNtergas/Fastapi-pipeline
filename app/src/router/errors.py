from pydantic import ValidationError

from router.schema import Classification


class PipelineError(Exception):
    """Base exception for pipeline errors."""


class LLMError(PipelineError):
    """Base exception for LLM errors."""


class LLMEmptyResponseError(LLMError):
    """Raised when LLM returns no content."""

    def __init__(self) -> None:
        super().__init__("LLM returned empty response.")


class LLMInvalidResponseError(LLMError):
    """Raised when LLM response does not match Classification schema."""

    def __init__(self, error: ValidationError) -> None:
        self.validation_error = error
        super().__init__(
            "LLM returned invalid classification response."
        )


def parse_classification(
    content: str | None,
) -> Classification:
    if not content:
        raise LLMEmptyResponseError

    try:
        return Classification.model_validate_json(content)
    except ValidationError as error:
        raise LLMInvalidResponseError(error) from error