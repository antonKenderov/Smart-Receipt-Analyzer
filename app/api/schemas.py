from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.domain.extraction import ExtractionMethod
from app.domain.invoice import StoredReceipt
from app.domain.validation import ValidationStatus


class ReceiptSummary(BaseModel):
    id: UUID
    invoice_number: str | None
    invoice_date: date | None
    issuer_name: str | None
    total_amount: Decimal | None
    currency: str | None
    extraction_method: ExtractionMethod
    validation_status: ValidationStatus
    line_item_count: int
    has_report: bool
    source_filename: str
    created_at: datetime

    @classmethod
    def from_domain(cls, receipt: StoredReceipt) -> "ReceiptSummary":
        return cls(
            id=receipt.id,
            invoice_number=receipt.invoice_number,
            invoice_date=receipt.invoice_date,
            issuer_name=receipt.issuer_name,
            total_amount=receipt.total_amount,
            currency=receipt.currency,
            extraction_method=receipt.extraction_method,
            validation_status=receipt.validation_status,
            line_item_count=len(receipt.line_items),
            has_report=receipt.report_path is not None,
            source_filename=receipt.source_filename,
            created_at=receipt.created_at,
        )


class ErrorResponse(BaseModel):
    code: str
    detail: str
