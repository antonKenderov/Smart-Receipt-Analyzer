"""Every failure the extraction pipeline is allowed to show the outside world.

The API layer catches ExtractionError and nothing else. Library-specific
exceptions - pdfminer.PDFSyntaxError, pdf2image errors, PIL errors - are
translated into one of these before they cross a module boundary.

`code` is a stable machine-readable slug, safe to put in an HTTP response
body; `status` is the HTTP status the API layer should answer with.
"""


class ExtractionError(Exception):
    code = "extraction_failed"
    status = 422

    def __init__(self, message: str, *, filename: str | None = None):
        super().__init__(message)
        self.message = message
        self.filename = filename

    def __str__(self) -> str:
        if self.filename:
            return f"{self.filename}: {self.message}"
        return self.message


class SourceNotFoundError(ExtractionError):
    code = "not_found"
    status = 404


class InvalidPDFError(ExtractionError):
    """Not a PDF at all, or a PDF too damaged to parse."""

    code = "invalid_pdf"
    status = 400


class EncryptedPDFError(ExtractionError):
    """Password-protected, or encrypted with a scheme we cannot read."""

    code = "encrypted_pdf"
    status = 400


class FileTooLargeError(ExtractionError):
    code = "file_too_large"
    status = 413


class TooManyPagesError(ExtractionError):
    code = "too_many_pages"
    status = 413


class EmptyDocumentError(ExtractionError):
    """A structurally valid PDF that contains no pages."""

    code = "empty_document"
    status = 400


class NoTextFoundError(ExtractionError):
    """Neither the text layer nor OCR produced anything to send to the LLM."""

    code = "no_text_found"
    status = 422
