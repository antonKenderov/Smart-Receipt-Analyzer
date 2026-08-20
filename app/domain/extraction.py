from pydantic import BaseModel, Field
from enum import Enum

class ExtractionMethod(str, Enum):
    TEXT_LAYER = "text_layer"
    OCR = "ocr"

class ExtractionResult(BaseModel):
    text: str
    method: ExtractionMethod
    page_count: int
    char_count: int
    warnings: list[str] = Field(default_factory=list)

