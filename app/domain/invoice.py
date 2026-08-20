from pydantic import BaseModel
from datetime import date
from decimal import Decimal

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