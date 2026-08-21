import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.db.session import init_db
from app.services.errors import ExtractionError

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

DESCRIPTION = """
Upload a PDF invoice, get structured data and a PDF expense report.

The embedded text layer is read first; OCR runs only when there is not enough
of one. An LLM then parses the text into an invoice and, in a separate call,
assigns a spending category to each line and corrects OCR damage in the
descriptions. The arithmetic is checked before anything is stored.

`POST /api/receipts` is the slow one: a scanned document runs OCR and two LLM
calls and can take a minute. Uploading a file that was processed before
returns the existing receipt instead of paying for it twice.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Smart Receipt Analyzer",
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.exception_handler(ExtractionError)
def extraction_error_handler(request: Request, exc: ExtractionError) -> JSONResponse:
    logger.info("%s -> %d %s", request.url.path, exc.status, exc.code)
    return JSONResponse(
        status_code=exc.status,
        content={"code": exc.code, "detail": str(exc)},
    )


@app.get("/health", tags=["health"], summary="Liveness check")
def health() -> dict[str, str]:
    return {"status": "ok"}
