import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from app.domain.invoice import Invoice

logger = logging.getLogger(__name__)

LINE_ITEM_TOLERANCE = Decimal("0.02")
AGGREGATE_TOLERANCE = Decimal("0.05")
KNOWN_CURRENCIES = {"GBP", "EUR", "USD", "BGN"}


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class ValidationStatus(str, Enum):
    CLEAN = "clean"
    FLAGGED = "flagged"
    INCONSISTENT = "inconsistent"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: Severity
    message: str
    field: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def status(self) -> ValidationStatus:
        if self.errors:
            return ValidationStatus.INCONSISTENT
        if self.warnings:
            return ValidationStatus.FLAGGED
        return ValidationStatus.CLEAN

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


def _issue(
    code: str, severity: Severity, message: str, *, field: str | None = None
) -> ValidationIssue:
    return ValidationIssue(code=code, severity=severity, message=message, field=field)


def _check_line_items_present(invoice: Invoice) -> list[ValidationIssue]:
    if not invoice.line_items:
        return [
            _issue(
                "no_line_items",
                Severity.ERROR,
                "Invoice has no line items",
                field="line_items",
            )
        ]
    return []


def _check_line_item_arithmetic(invoice: Invoice) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for i, item in enumerate(invoice.line_items):
        expected = item.quantity * item.unit_price
        if abs(expected - item.amount) > LINE_ITEM_TOLERANCE:
            issues.append(
                _issue(
                    "line_item_arithmetic_mismatch",
                    Severity.ERROR,
                    f"Row {item.position}: {item.quantity} x {item.unit_price} "
                    f"= {expected}, but amount is {item.amount}",
                    field=f"line_items[{i}].amount",
                )
            )
    return issues


def _check_subtotal(invoice: Invoice) -> list[ValidationIssue]:
    if invoice.subtotal is None or not invoice.line_items:
        return []

    computed = sum(
        (item.amount for item in invoice.line_items),
        start=Decimal("0"),
    )
    if abs(computed - invoice.subtotal) > AGGREGATE_TOLERANCE:
        return [
            _issue(
                "subtotal_mismatch",
                Severity.ERROR,
                f"Line items sum to {computed}, but subtotal is "
                f"{invoice.subtotal}",
                field="subtotal",
            )
        ]
    return []


def _check_total(invoice: Invoice) -> list[ValidationIssue]:
    if invoice.subtotal is None or invoice.total_amount is None:
        return []

    tax = invoice.tax_amount or Decimal("0")
    expected = invoice.subtotal + tax
    if abs(expected - invoice.total_amount) > AGGREGATE_TOLERANCE:
        return [
            _issue(
                "total_mismatch",
                Severity.ERROR,
                f"subtotal ({invoice.subtotal}) + tax ({tax}) "
                f"= {expected}, but total is {invoice.total_amount}",
                field="total_amount",
            )
        ]
    return []


def _check_line_item_sanity(invoice: Invoice) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for i, item in enumerate(invoice.line_items):
        if item.quantity <= 0:
            issues.append(
                _issue(
                    "non_positive_quantity",
                    Severity.WARNING,
                    f"Row {item.position}: quantity is {item.quantity}",
                    field=f"line_items[{i}].quantity",
                )
            )
        if item.unit_price < 0:
            issues.append(
                _issue(
                    "negative_unit_price",
                    Severity.WARNING,
                    f"Row {item.position}: unit_price is {item.unit_price}",
                    field=f"line_items[{i}].unit_price",
                )
            )
    return issues

_EXPECTED_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("invoice_number", "missing_invoice_number", "invoice number"),
    ("invoice_date", "missing_invoice_date", "invoice date"),
    ("issuer_name", "missing_issuer_name", "issuer name"),
    ("issuer_id", "missing_issuer_id", "issuer VAT/tax ID"),
    ("receiver_name", "missing_receiver_name", "receiver name"),
    ("receiver_id", "missing_receiver_id", "receiver VAT/tax ID"),
    ("subtotal", "missing_subtotal", "subtotal"),
    ("tax_amount", "missing_tax_amount", "tax amount"),
    ("total_amount", "missing_total_amount", "total amount"),
    ("currency", "missing_currency", "currency"),
)


def _check_presence(invoice: Invoice) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for attr, code, label in _EXPECTED_FIELDS:
        if getattr(invoice, attr) is None:
            issues.append(
                _issue(
                    code,
                    Severity.WARNING,
                    f"Missing {label}",
                    field=attr,
                )
            )
    return issues


def _check_currency(invoice: Invoice) -> list[ValidationIssue]:
    if invoice.currency is None or invoice.currency in KNOWN_CURRENCIES:
        return []
    return [
        _issue(
            "unrecognized_currency",
            Severity.WARNING,
            f"Currency '{invoice.currency}' is not one of "
            f"{sorted(KNOWN_CURRENCIES)}",
            field="currency",
        )
    ]


def validate_invoice(invoice: Invoice) -> ValidationResult:
    issues: list[ValidationIssue] = []

    issues += _check_line_items_present(invoice)
    if invoice.line_items:
        issues += _check_line_item_arithmetic(invoice)
        issues += _check_line_item_sanity(invoice)
    issues += _check_subtotal(invoice)
    issues += _check_total(invoice)
    issues += _check_presence(invoice)
    issues += _check_currency(invoice)

    result = ValidationResult(issues=issues)
    logger.info(
        "Invoice validation: %s (%d error(s), %d warning(s))",
        result.status.value,
        len(result.errors),
        len(result.warnings),
    )
    return result
