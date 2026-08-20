from dataclasses import dataclass, field
from enum import Enum


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
