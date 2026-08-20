import logging
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import LLMCall, LLMStage
from app.db.models import LineItem as LineItemRow
from app.db.models import Receipt as ReceiptRow
from app.domain.extraction import ExtractionMethod
from app.domain.invoice import (
    Category,
    EnrichedInvoice,
    EnrichedLineItem,
    StoredReceipt,
)
from app.domain.validation import Severity, ValidationIssue, ValidationResult

logger = logging.getLogger(__name__)


def _issues_to_json(issues: list[ValidationIssue]) -> list[dict]:
    return [asdict(issue) for issue in issues]


def _issues_from_json(raw: list[dict] | None) -> list[ValidationIssue]:
    if not raw:
        return []

    issues: list[ValidationIssue] = []
    for item in raw:
        try:
            issues.append(
                ValidationIssue(
                    code=item["code"],
                    severity=Severity(item["severity"]),
                    message=item["message"],
                    field=item.get("field"),
                )
            )
        except (KeyError, ValueError, TypeError):
            logger.warning("Skipping unreadable validation issue: %r", item)
    return issues


def _to_domain(row: ReceiptRow) -> StoredReceipt:
    return StoredReceipt(
        id=row.id,
        invoice_number=row.invoice_number,
        invoice_date=row.invoice_date,
        issuer_name=row.issuer_name,
        issuer_id=row.issuer_id,
        receiver_name=row.receiver_name,
        receiver_id=row.receiver_id,
        line_items=[
            EnrichedLineItem(
                position=item.position,
                description=item.description,
                description_raw=item.description_raw,
                category=item.category,
                quantity=item.quantity,
                unit_price=item.unit_price,
                amount=item.amount,
            )
            for item in row.line_items
        ],
        subtotal=row.subtotal,
        tax_amount=row.tax_amount,
        total_amount=row.total_amount,
        currency=row.currency,
        extraction_method=row.extraction_method,
        validation_status=row.validation_status,
        validation_issues=_issues_from_json(row.validation_issues),
        source_filename=row.source_filename,
        file_hash=row.file_hash,
        report_path=row.report_path,
        created_at=row.created_at,
        processed_at=row.processed_at,
    )


class ReceiptRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _base_query(self):
        return select(ReceiptRow).options(selectinload(ReceiptRow.line_items))

    def add(
        self,
        invoice: EnrichedInvoice,
        *,
        extraction_method: ExtractionMethod,
        validation: ValidationResult,
        source_filename: str,
        file_hash: str,
        report_path: str | None = None,
        processed_at: datetime | None = None,
    ) -> StoredReceipt:
        row = ReceiptRow(
            invoice_number=invoice.invoice_number,
            invoice_date=invoice.invoice_date,
            issuer_name=invoice.issuer_name,
            issuer_id=invoice.issuer_id,
            receiver_name=invoice.receiver_name,
            receiver_id=invoice.receiver_id,
            subtotal=invoice.subtotal,
            tax_amount=invoice.tax_amount,
            total_amount=invoice.total_amount,
            currency=invoice.currency,
            extraction_method=extraction_method,
            validation_status=validation.status,
            validation_issues=_issues_to_json(validation.issues),
            source_filename=source_filename,
            file_hash=file_hash,
            report_path=report_path,
            processed_at=processed_at,
            line_items=[
                LineItemRow(
                    position=item.position,
                    description=item.description,
                    description_raw=item.description_raw,
                    category=item.category,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    amount=item.amount,
                )
                for item in invoice.line_items
            ],
        )

        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)

        logger.info(
            "Stored receipt %s (%s, %d line item(s), status=%s)",
            row.id,
            source_filename,
            len(row.line_items),
            validation.status.value,
        )
        return _to_domain(row)

    def get(self, receipt_id: UUID) -> StoredReceipt | None:
        row = self._session.scalars(
            self._base_query().where(ReceiptRow.id == receipt_id)
        ).one_or_none()
        return _to_domain(row) if row else None

    def get_by_file_hash(self, file_hash: str) -> StoredReceipt | None:
        row = self._session.scalars(
            self._base_query().where(ReceiptRow.file_hash == file_hash)
        ).one_or_none()
        return _to_domain(row) if row else None

    def list_receipts(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[StoredReceipt]:
        rows = self._session.scalars(
            self._base_query()
            .order_by(ReceiptRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [_to_domain(row) for row in rows]

    def set_report_path(
        self, receipt_id: UUID, report_path: str
    ) -> StoredReceipt | None:
        row = self._session.get(ReceiptRow, receipt_id)
        if row is None:
            return None

        row.report_path = report_path
        self._session.flush()
        return _to_domain(row)

    def mark_processed(
        self, receipt_id: UUID, processed_at: datetime
    ) -> StoredReceipt | None:
        row = self._session.get(ReceiptRow, receipt_id)
        if row is None:
            return None

        row.processed_at = processed_at
        self._session.flush()
        return _to_domain(row)

    def add_llm_call(
        self,
        receipt_id: UUID,
        *,
        stage: LLMStage,
        model: str,
        raw_response: dict,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self._session.add(
            LLMCall(
                receipt_id=receipt_id,
                stage=stage,
                model=model,
                raw_response=raw_response,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
            )
        )
        self._session.flush()

    def delete(self, receipt_id: UUID) -> bool:
        row = self._session.get(ReceiptRow, receipt_id)
        if row is None:
            return False

        self._session.delete(row)
        self._session.flush()
        logger.info("Deleted receipt %s", receipt_id)
        return True

    def totals_by_category(self, receipt_id: UUID) -> dict[Category, Decimal]:
        rows = self._session.execute(
            select(LineItemRow.category, LineItemRow.amount).where(
                LineItemRow.receipt_id == receipt_id
            )
        ).all()

        totals: dict[Category, Decimal] = {}
        for category, amount in rows:
            totals[category] = totals.get(category, Decimal("0")) + amount
        return totals
