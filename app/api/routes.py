import logging
import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.schemas import ErrorResponse, ReceiptSummary
from app.db.repository import ReceiptRepository
from app.db.session import get_session
from app.domain.invoice import StoredReceipt
from app.services.pipeline import process_invoice

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/receipts", tags=["receipts"])

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such receipt"}}


def _repo(session: Session = Depends(get_session)) -> ReceiptRepository:
    return ReceiptRepository(session)


def _load(repo: ReceiptRepository, receipt_id: UUID) -> StoredReceipt:
    receipt = repo.get(receipt_id)
    if receipt is None:
        raise HTTPException(
            status_code=404, detail=f"No receipt with id {receipt_id}"
        )
    return receipt


@router.post(
    "",
    response_model=StoredReceipt,
    summary="Upload and process an invoice",
    responses={
        400: {"model": ErrorResponse, "description": "Not a usable PDF"},
        413: {"model": ErrorResponse, "description": "Too large, or too many pages"},
        422: {"model": ErrorResponse, "description": "No text could be extracted"},
    },
)
def upload_receipt(file: UploadFile = File(...)) -> StoredReceipt:
    name = Path(file.filename or "upload.pdf").name or "upload.pdf"
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = Path(tmpdir) / name
        with temp_path.open("wb") as target:
            shutil.copyfileobj(file.file, target)

        return process_invoice(temp_path, source_filename=name)


@router.get(
    "",
    response_model=list[ReceiptSummary],
    summary="List processed receipts, newest first",
)
def list_receipts(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: ReceiptRepository = Depends(_repo),
) -> list[ReceiptSummary]:
    return [
        ReceiptSummary.from_domain(r)
        for r in repo.list_receipts(limit=limit, offset=offset)
    ]


@router.get(
    "/{receipt_id}",
    response_model=StoredReceipt,
    summary="One receipt, with line items and validation findings",
    responses=_NOT_FOUND,
)
def get_receipt(
    receipt_id: UUID, repo: ReceiptRepository = Depends(_repo)
) -> StoredReceipt:
    return _load(repo, receipt_id)


@router.get(
    "/{receipt_id}/report",
    response_class=FileResponse,
    summary="Download the generated PDF expense report",
    responses={
        200: {"content": {"application/pdf": {}}},
        **_NOT_FOUND,
    },
)
def get_report(
    receipt_id: UUID, repo: ReceiptRepository = Depends(_repo)
) -> FileResponse:
    receipt = _load(repo, receipt_id)

    if not receipt.report_path:
        raise HTTPException(
            status_code=404, detail="This receipt has no report recorded"
        )

    path = Path(receipt.report_path)
    if not path.is_file():
        logger.warning("Report for %s is missing at %s", receipt_id, path)
        raise HTTPException(
            status_code=404,
            detail=f"Report file is missing at {path.name}",
        )

    return FileResponse(path, media_type="application/pdf", filename=path.name)
