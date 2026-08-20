import json
import logging
from time import perf_counter

from litellm import completion

from app.config import get_settings
from app.domain.invoice import (
    EnrichedInvoice,
    EnrichedLineItem,
    EnrichmentResponse,
    Invoice,
)
from app.domain.llm import LLMCallRecord
from app.llm.prompts import ENRICHMENT_PROMPT, EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


def _as_dict(response) -> dict:

    for attempt in (
        lambda: response.model_dump(mode="json"),
        lambda: json.loads(response.json()),
        lambda: dict(response),
    ):
        try:
            return attempt()
        except Exception:
            continue

    logger.warning("Could not serialise the LLM response; storing its repr")
    return {"unserialisable_repr": repr(response)}


def _record(response, duration_ms: int) -> LLMCallRecord:
    usage = getattr(response, "usage", None)
    return LLMCallRecord(
        model=getattr(response, "model", None) or get_settings().llm_model,
        raw_response=_as_dict(response),
        duration_ms=duration_ms,
        input_tokens=getattr(usage, "prompt_tokens", None),
        output_tokens=getattr(usage, "completion_tokens", None),
    )


def _call(system_prompt: str, user_content: str, response_format):
    settings = get_settings()
    started = perf_counter()
    response = completion(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format=response_format,
        temperature=0,
        timeout=settings.llm_timeout_seconds,
        num_retries=2,
    )
    duration_ms = int((perf_counter() - started) * 1000)
    return response, _record(response, duration_ms)


def extract_invoice(text: str) -> tuple[Invoice, LLMCallRecord]:
    response, record = _call(EXTRACTION_PROMPT, text, Invoice)
    invoice = Invoice.model_validate_json(response.choices[0].message.content)
    return invoice, record


def enrich_invoice(invoice: Invoice) -> tuple[EnrichedInvoice, LLMCallRecord]:
    rows = [
        {"position": item.position, "description": item.description}
        for item in invoice.line_items
    ]

    response, record = _call(
        ENRICHMENT_PROMPT, json.dumps(rows), EnrichmentResponse
    )
    enrichment = EnrichmentResponse.model_validate_json(
        response.choices[0].message.content
    )
    by_position = {row.position: row for row in enrichment.line_items}

    enriched_items: list[EnrichedLineItem] = []
    for item in invoice.line_items:
        row = by_position.get(item.position)
        if row is None:
            raise ValueError(
                f"Enrichment response is missing line item {item.position}"
            )
        enriched_items.append(
            EnrichedLineItem(
                position=item.position,
                description=row.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                amount=item.amount,
                category=row.category,
                description_raw=item.description,
            )
        )

    enriched = EnrichedInvoice(
        **invoice.model_dump(exclude={"line_items"}),
        line_items=enriched_items,
        summary=enrichment.summary,
    )
    return enriched, record
