from dataclasses import dataclass


@dataclass(frozen=True)
class LLMCallRecord:
    model: str
    raw_response: dict
    duration_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
