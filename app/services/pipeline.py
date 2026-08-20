import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from app.config import get_settings
from app.db.models import LLMStage
from app.db.repository import ReceiptRepository
from app.db.session import session_scope
from app.domain.invoice import (
    Category,
    EnrichedInvoice,
    EnrichedLineItem,
    Invoice,
    StoredReceipt,
)
from app.domain.llm import LLMCallRecord
from app.extraction.extractor import extract_text
from app.extraction.validation import validate_pdf
from app.llm.client import enrich_invoice, extract_invoice
from app.reports.generator import generate_report
from app.services.validation import validate_invoice

logger = logging.getLogger(__name__)

_HASH_CHUNK = 1 << 20


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _without_enrichment(invoice: Invoice) -> EnrichedInvoice:
    return EnrichedInvoice(
        **invoice.model_dump(exclude={"line_items"}),
        line_items=[
            EnrichedLineItem(
                **item.model_dump(),
                category=Category.OTHER,
                description_raw=item.description,
            )
            for item in invoice.line_items
        ],
    )


def _record_call(repo, receipt_id, stage: LLMStage, call: LLMCallRecord) -> None:
    repo.add_llm_call(
        receipt_id,
        stage=stage,
        model=call.model,
        raw_response=call.raw_response,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        duration_ms=call.duration_ms,
    )


def process_invoice(pdf_path: Path | str) -> StoredReceipt:
    path = Path(pdf_path)
    validate_pdf(path)
    digest = file_hash(path)

    with session_scope() as session:
        repo = ReceiptRepository(session)

        already = repo.get_by_file_hash(digest)
        if already is not None:
            logger.info("'%s' already processed as %s", path.name, already.id)
            return already

        extraction = extract_text(path)
        invoice, extraction_call = extract_invoice(extraction.text)
        validation = validate_invoice(invoice)

        if validation.has_errors:
            logger.warning(
                "'%s' failed validation (%d error(s)); skipping enrichment",
                path.name,
                len(validation.errors),
            )
            enriched, enrichment_call = _without_enrichment(invoice), None
        else:
            enriched, enrichment_call = enrich_invoice(invoice)

        receipt = repo.add(
            enriched,
            extraction_method=extraction.method,
            validation=validation,
            source_filename=path.name,
            file_hash=digest,
            processed_at=datetime.now(timezone.utc),
        )
        report = generate_report(
            enriched,
            get_settings().output_dir,
            filename=f"report-{receipt.id}.pdf",
        )
        receipt = repo.set_report_path(receipt.id, str(report))

        _record_call(repo, receipt.id, LLMStage.EXTRACTION, extraction_call)
        if enrichment_call is not None:
            _record_call(repo, receipt.id, LLMStage.ENRICHMENT, enrichment_call)

        return receipt
