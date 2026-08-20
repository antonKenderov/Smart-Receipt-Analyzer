from pydantic import BaseModel, Field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from app.domain.extraction import ExtractionMethod
from app.domain.validation import ValidationIssue, ValidationStatus

class Category(str, Enum):
    DAIRY = "Dairy"
    BAKERY = "Bakery"
    MEAT = "Meat"
    PRODUCE = "Produce"
    BEVERAGES = "Beverages"
    PANTRY = "Pantry"
    HOUSEHOLD = "Household"
    PERSONAL_CARE = "Personal Care"
    OFFICE = "Office"
    ELECTRONICS = "Electronics"
    SERVICES = "Services"
    OTHER = "Other"

class LineItem(BaseModel):
    position: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal

class Invoice(BaseModel):
    invoice_number: str | None = None
    invoice_date: date | None = None
    issuer_name: str | None = None
    issuer_id: str | None = None
    receiver_name: str | None = None
    receiver_id: str | None = None
    line_items: list[LineItem]
    subtotal: Decimal | None = None
    tax_amount: Decimal | None = None
    total_amount: Decimal | None = None
    currency: str | None = None

class EnrichedLineItem(LineItem):
    category: Category
    description_raw: str

class EnrichedInvoice(Invoice):
    line_items: list[EnrichedLineItem]
    summary: str | None = None

class EnrichmentRow(BaseModel):
    position: int
    description: str
    category: Category

class EnrichmentResponse(BaseModel):
    line_items: list[EnrichmentRow]
    summary: str

class StoredReceipt(EnrichedInvoice):
    id: UUID
    extraction_method: ExtractionMethod
    validation_status: ValidationStatus
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    source_filename: str
    file_hash: str
    report_path: str | None = None
    created_at: datetime
    processed_at: datetime | None = None
