import json

from litellm import completion

from app.config import get_settings
from app.domain.invoice import (
    EnrichedInvoice,
    EnrichedLineItem,
    EnrichmentResponse,
    Invoice,
)
from app.llm.prompts import ENRICHMENT_PROMPT, EXTRACTION_PROMPT


def extract_invoice(text: str) -> Invoice:
    settings = get_settings()

    response = completion(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format=Invoice,
        temperature=0,
        timeout=settings.llm_timeout_seconds,
        num_retries=2,
    )

    content = response.choices[0].message.content
    return Invoice.model_validate_json(content)


def enrich_invoice(invoice: Invoice) -> EnrichedInvoice:
    settings = get_settings()

    rows = [
        {"position": item.position, "description": item.description}
        for item in invoice.line_items
    ]

    response = completion(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": ENRICHMENT_PROMPT},
            {"role": "user", "content": json.dumps(rows)},
        ],
        response_format=EnrichmentResponse,
        temperature=0,
        timeout=settings.llm_timeout_seconds,
        num_retries=2,
    )

    content = response.choices[0].message.content
    enrichment = EnrichmentResponse.model_validate_json(content)
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

    return EnrichedInvoice(
        **invoice.model_dump(exclude={"line_items"}),
        line_items=enriched_items,
    )
