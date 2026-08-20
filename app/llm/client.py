from litellm import completion
from app.domain.invoice import Invoice
from app.config import get_settings
from app.llm.prompts import EXTRACTION_PROMPT

def extract_invoice(text: str) -> Invoice:
    confSettings = get_settings()

    try:
        response = completion(
            model= confSettings.llm_model,
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": text}
            ],
            response_format=Invoice,
            temperature=0,
            timeout=confSettings.llm_timeout_seconds,
            num_retries=2,
        )
    except Exception as err:
        raise  err

    content = response.choices[0].message.content
    try:
        return Invoice.model_validate_json(content)
    except Exception as err:
        raise err