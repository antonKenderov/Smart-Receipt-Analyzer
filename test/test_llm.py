import pytest
from datetime import date

from app.extraction.extractor import extract_text
from app.llm.client import extract_invoice

def test_llm_should_return_invoice():
    items = [
        {
            "id": 1,
            "description": "A4 Paper Ream (500 sheets)",
            "qty": 20,
            "unit_price": 4.50,
            "amount": 90.00,
        },
        {
            "id": 2,
            "description": "Ballpoint Pens (box of 12)",
            "qty": 15,
            "unit_price": 3.20,
            "amount": 48.00,
        },
        {
            "id": 3,
            "description": "Desk Organizer",
            "qty": 6,
            "unit_price": 12.75,
            "amount": 76.50,
        },
        {
            "id": 4,
            "description": "Wireless Mouse",
            "qty": 8,
            "unit_price": 18.90,
            "amount": 151.20,
        },
        {
            "id": 5,
            "description": "Sticky Notes (pack of 6)",
            "qty": 25,
            "unit_price": 2.10,
            "amount": 52.50,
        },
        {
            "id": 6,
            "description": "Ring Binder A4",
            "qty": 12,
            "unit_price": 5.60,
            "amount": 67.20,
        },
        {
            "id": 7,
            "description": "Whiteboard Markers (set)",
            "qty": 10,
            "unit_price": 6.40,
            "amount": 64.00,
        },
        {
            "id": 8,
            "description": "Stapler Heavy Duty",
            "qty": 5,
            "unit_price": 9.30,
            "amount": 46.50,
        },
        {
            "id": 9,
            "description": "USB Flash Drive 32GB",
            "qty": 10,
            "unit_price": 11.20,
            "amount": 112.00,
        },
    ]
    result = extract_text("samples/7.pdf")
    invoice = extract_invoice(result.text)

    assert invoice.invoice_number == "1"
    assert invoice.invoice_date == date(2026, 8, 10)
    assert invoice.issuer_name == "OfficePro Supplies Inc"
    assert invoice.issuer_id == "GB456789123"
    assert invoice.receiver_name == "BrightPath Consulting"
    assert invoice.receiver_id == "GB321654987"
    assert invoice.line_items == items
    assert invoice.subtotal == 707.90
    assert invoice.tax_amount == 141.58
    assert invoice.total_amount == 849.48
    assert invoice.currency == "£"