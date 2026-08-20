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
    code = "invalid_pdf"
    status = 400


class EncryptedPDFError(ExtractionError):
    code = "encrypted_pdf"
    status = 400


class FileTooLargeError(ExtractionError):
    code = "file_too_large"
    status = 413


class TooManyPagesError(ExtractionError):
    code = "too_many_pages"
    status = 413


class EmptyDocumentError(ExtractionError):
    code = "empty_document"
    status = 400


class NoTextFoundError(ExtractionError):
    code = "no_text_found"
    status = 422
