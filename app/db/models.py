import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

import sqlalchemy
from sqlalchemy import (
    CHAR,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Numeric,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.extraction import ExtractionMethod
from app.domain.invoice import Category
from app.domain.validation import ValidationStatus


class LLMStage(str, Enum):
    EXTRACTION = "extraction"
    ENRICHMENT = "enrichment"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enum_column(enum_cls: type[Enum], name: str) -> SQLEnum:
    return SQLEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda e: [m.value for m in e],
    )


class Base(DeclarativeBase):
    pass


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=sqlalchemy.text("gen_random_uuid()"),
    )

    invoice_number: Mapped[str | None] = mapped_column(Text)
    invoice_date: Mapped[date | None] = mapped_column(Date)

    issuer_name: Mapped[str | None] = mapped_column(Text)
    issuer_id: Mapped[str | None] = mapped_column(Text)
    receiver_name: Mapped[str | None] = mapped_column(Text)
    receiver_id: Mapped[str | None] = mapped_column(Text)

    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    summary: Mapped[str | None] = mapped_column(Text)

    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        _enum_column(ExtractionMethod, "extraction_method")
    )
    validation_status: Mapped[ValidationStatus] = mapped_column(
        _enum_column(ValidationStatus, "validation_status")
    )
    validation_issues: Mapped[list] = mapped_column(JSONB, default=list)

    source_filename: Mapped[str] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    report_path: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    line_items: Mapped[list["LineItem"]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="LineItem.position",
    )
    llm_calls: Mapped[list["LLMCall"]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="LLMCall.created_at",
    )


class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=sqlalchemy.text("gen_random_uuid()"),
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), index=True
    )

    position: Mapped[int]
    description: Mapped[str] = mapped_column(Text)
    description_raw: Mapped[str] = mapped_column(Text)
    category: Mapped[Category] = mapped_column(_enum_column(Category, "category"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    receipt: Mapped["Receipt"] = relationship(back_populates="line_items")


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=sqlalchemy.text("gen_random_uuid()"),
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), index=True
    )

    stage: Mapped[LLMStage] = mapped_column(_enum_column(LLMStage, "llm_stage"))
    model: Mapped[str] = mapped_column(Text)
    raw_response: Mapped[dict] = mapped_column(JSONB)

    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    duration_ms: Mapped[int | None]

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    receipt: Mapped["Receipt"] = relationship(back_populates="llm_calls")
