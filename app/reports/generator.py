import logging
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.domain.invoice import Category, EnrichedInvoice

logger = logging.getLogger(__name__)

MISSING = "-"

_STYLES = getSampleStyleSheet()
_TITLE = ParagraphStyle("ReportTitle", parent=_STYLES["Title"], fontSize=18, spaceAfter=2 * mm)
_HEADING = ParagraphStyle("ReportHeading", parent=_STYLES["Heading2"], fontSize=12, spaceBefore=6 * mm)
_BODY = _STYLES["BodyText"]
_CELL = ParagraphStyle("Cell", parent=_BODY, fontSize=9, leading=11)
_CELL_RIGHT = ParagraphStyle("CellRight", parent=_CELL, alignment=TA_RIGHT)
_NOTE = ParagraphStyle("Note", parent=_BODY, fontSize=9, leading=12, textColor=colors.HexColor("#333333"))

_GRID = colors.HexColor("#B0B0B0")
_HEADER_BG = colors.HexColor("#E8E8E8")


def _money(value: Decimal | None, currency: str | None) -> str:
    if value is None:
        return MISSING
    suffix = f" {currency}" if currency else ""
    return f"{value:,.2f}{suffix}"


def _quantity(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _sanitise(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem).strip("_")
    return f"{stem or 'report'}.pdf"


def _report_filename(invoice: EnrichedInvoice) -> str:
    if invoice.invoice_number:
        return f"report-{invoice.invoice_number}.pdf"

    return f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf"


def _header_table(invoice: EnrichedInvoice) -> Table:
    rows = [
        ["Vendor:", invoice.issuer_name or MISSING],
        ["Date:", invoice.invoice_date.isoformat() if invoice.invoice_date else MISSING],
        ["Invoice #:", invoice.invoice_number or MISSING],
    ]
    if invoice.receiver_name:
        rows.append(["Bill to:", invoice.receiver_name])

    table = Table(rows, colWidths=[28 * mm, None], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _line_items_table(invoice: EnrichedInvoice) -> Table:
    header = ["#", "Item", "Category", "Qty", "Unit Price", "Amount"]
    rows = [header]
    for item in invoice.line_items:
        rows.append(
            [
                str(item.position),
                # A description can be long enough to need wrapping; a bare
                # string would run off the page instead.
                Paragraph(item.description, _CELL),
                item.category.value,
                _quantity(item.quantity),
                _money(item.unit_price, None),
                _money(item.amount, None),
            ]
        )

    table = Table(
        rows,
        colWidths=[10 * mm, None, 28 * mm, 16 * mm, 22 * mm, 24 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def totals_by_category(invoice: EnrichedInvoice) -> dict[Category, Decimal]:
    totals: dict[Category, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in invoice.line_items:
        totals[item.category] += item.amount
    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))


def _summary_table(invoice: EnrichedInvoice) -> Table:
    currency = invoice.currency
    rows = [
        [category.value, _money(amount, None)]
        for category, amount in totals_by_category(invoice).items()
    ]

    separator = len(rows)
    rows.append(["Subtotal", _money(invoice.subtotal, None)])
    if invoice.tax_amount is not None:
        rows.append(["Tax", _money(invoice.tax_amount, None)])
    rows.append(["TOTAL", _money(invoice.total_amount, currency)])

    table = Table(rows, colWidths=[60 * mm, 40 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, separator), (-1, separator), 0.6, _GRID),
                ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.black),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def generate_report(
    invoice: EnrichedInvoice,
    output_dir: Path,
    *,
    filename: str | None = None,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / _sanitise(filename or _report_filename(invoice))

    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        title=f"Expense Report {invoice.invoice_number or ''}".strip(),
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )

    story = [
        Paragraph("EXPENSE REPORT", _TITLE),
        _header_table(invoice),
        Spacer(1, 6 * mm),
        _line_items_table(invoice),
        KeepTogether(
            [
                Paragraph("Category Summary", _HEADING),
                _summary_table(invoice),
            ]
        ),
    ]

    if invoice.summary:
        story += [
            Spacer(1, 5 * mm),
            Paragraph(invoice.summary, _NOTE),
        ]

    document.build(story)
    logger.info(
        "Wrote report %s (%d line item(s))", path.name, len(invoice.line_items)
    )
    return path
