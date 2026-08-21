# Smart Receipt Analyzer

Takes a PDF invoice, pulls the text out of it, and turns that text into
structured data: issuer, receiver, dates, line items, totals, and a spending
category per item. It is built to read any invoice layout rather than a fixed
template, which is why the parsing is done by a language model instead of
regular expressions.

PDF in, structured records in PostgreSQL, PDF expense report out, over a REST
API. The whole flow runs from `docker compose up`.

## The flow

One function knows the whole sequence — `process_invoice()` in
`app/services/pipeline.py`. Everything else is a module it calls.

```
validate_pdf        magic bytes, size, page count, encryption
  -> file_hash      SHA-256; a file already processed returns its existing
                    receipt here, before any paid work
  -> extract_text   text layer if there is one, OCR if there is not
  -> extract_invoice   LLM call 1: raw text -> Invoice
  -> validate_invoice  arithmetic and presence checks
  -> enrich_invoice    LLM call 2: categories, corrections, summary
                       skipped entirely when validation found errors
  -> repository.add    one transaction: receipt, line items, both raw responses
  -> generate_report   PDF to output/, path recorded on the receipt
```

| Module | Responsibility |
| --- | --- |
| `app/api/` | four endpoints and their response shapes |
| `app/services/pipeline.py` | the orchestrator above - the only module that knows the whole flow |
| `app/services/validation.py` | arithmetic and presence checks on the extracted invoice |
| `app/services/errors.py` | one `ExtractionError` hierarchy carrying a slug and an HTTP status |
| `app/extraction/validation.py` | input validation - magic bytes, size, page count, encryption |
| `app/extraction/extractor.py` | `extract_text()` - the hybrid orchestrator |
| `app/extraction/text_layer.py` | pdfplumber text layer with table detection |
| `app/extraction/pdf_reader.py` | rasterisation via pdf2image / poppler |
| `app/extraction/image_reader.py` | EasyOCR (en + bg) with line reconstruction |
| `app/llm/client.py` | both LLM calls, each returning its parsed result and its raw response |
| `app/llm/prompts.py` | the two prompts |
| `app/db/` | schema, session scope, and a repository that speaks domain models |
| `app/reports/generator.py` | `EnrichedInvoice` -> PDF expense report |
| `app/domain/` | Pydantic models - no dependency on any other layer |

`app/domain/` depends on nothing. `services`, `db`, `llm`, `reports` and `api`
depend on `domain`, never on each other. The one exception is deliberate:
`pipeline.py` imports from all of them, because being the single place that
knows the sequence is its job.

## Setup

Requires Docker with Compose v2. The only file you need to edit is `.env`, and
only to add your OpenAI key.

**bash**

```bash
cp .env.example .env
```

**PowerShell**

```powershell
Copy-Item .env.example .env
```

Then put your key in `OPENAI_API_KEY=` in `.env`. The Postgres credentials in
that file already have working defaults; leave them alone. After that, the
commands are identical in both shells:

```bash
docker compose build
```

```bash
docker compose up
```

**The first build takes 10-20 minutes.** It installs CPU-only PyTorch (a ~190 MB
wheel) and then downloads the EasyOCR model weights so they are baked into the
image rather than fetched on the first request. It has not hung. Later builds
reuse those layers and finish in seconds unless `requirements.txt` or the
Dockerfile changed.

A working start looks like this: `db` logs `database system is ready to accept
connections` and its healthcheck goes green, then `app` starts and logs
`Uvicorn running on http://0.0.0.0:8000`. Check it:

```bash
curl http://localhost:8000/health
```

That returns `{"status":"ok"}`. `app` has no restart policy on purpose, so if it
crashes you see a stopped container rather than a silent restart loop.

## Using it

**Swagger UI is at http://localhost:8000/docs** — upload a file and read the
response there, no client needed.

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/api/receipts` | Upload a PDF, run the whole pipeline, return the stored receipt |
| `GET` | `/api/receipts` | List receipts, newest first (`limit`, `offset`); no line items |
| `GET` | `/api/receipts/{id}` | One receipt with line items and validation findings |
| `GET` | `/api/receipts/{id}/report` | Download the generated PDF report |

Upload one of the bundled samples:

```bash
curl -X POST http://localhost:8000/api/receipts -F "file=@samples/7.pdf"
```

The response is the full receipt: a `uuid`, the parsed invoice, a `category` on
every line item, `validation_status`, and `report_path`. Measured on the bundled
samples: about **8 seconds** for `7.pdf` through the text layer, about **36
seconds** for `8.pdf` through OCR. Both are two LLM round-trips; the difference
is the OCR pass.

Upload the same file again and it returns in **under a tenth of a second** with
the same `id`. The pipeline recognises it by content hash before spending
anything, so a renamed copy matches too.

List what has been processed:

```bash
curl http://localhost:8000/api/receipts
```

Download the report, substituting an `id` from above:

```bash
curl -o report.pdf http://localhost:8000/api/receipts/<id>/report
```

Reports also land in `./output/` on the host, named after the receipt id.

Failures return a `code` alongside the message, so a client can branch without
parsing prose:

```json
{"code": "invalid_pdf", "detail": "notes.pdf: Not a PDF: missing %PDF- header (the extension is not evidence)"}
```

`invalid_pdf`, `encrypted_pdf` and `empty_document` are `400`; `file_too_large`
and `too_many_pages` are `413`; `no_text_found` is `422`; an unknown id is
`404`. Every one of them comes from a single `ExtractionError` hierarchy that
already carries its own status, so the API layer never sees a pdfminer or
EasyOCR exception — and the absolute paths those libraries put in their
messages never reach a client, because the hierarchy only ever carries a
basename.

## Architecture

### Hybrid extraction: text layer first, OCR only as fallback

`extract_text()` in `app/extraction/extractor.py` is the only place that knows
both pdfplumber and EasyOCR exist. It reads the embedded text layer first and
falls back to rasterisation plus OCR only when that layer is too thin.

The order matters. Rasterising a digital-born PDF to recognise characters that
are already embedded in the file introduces recognition errors into text that
was previously exact, and it throws away the column structure that
`layout=True` preserves. OCR is strictly the worse option whenever a real text
layer exists.

The threshold is 100 characters per page, and it was measured rather than
guessed. Across the nine bundled samples the split is total:

| Branch | Samples | Characters per page |
| --- | --- | --- |
| Text layer | `1.pdf` - `7.pdf` | 920, 936, 953, 1168, 1299, 1891, 1962 |
| OCR | `8.pdf`, `7_scanned.pdf` | 0 |

There is nothing between 0 and 920, so 100 sits in an empty gap rather than on a
boundary anyone has to defend. `test_threshold_sits_in_an_empty_gap` enforces
that: it recomputes the densities and fails if the constant drifts out of the
measured gap, which for the current sample set is the band 100-184.

`USE_LAYOUT = True` costs about 1.55x the characters of `layout=False` (1962 vs
1267 on `7.pdf`) and buys the horizontal alignment that keeps the issuer block
from merging into the invoice metadata.

### Two LLM calls, not one

`extract_invoice()` turns raw text into an `Invoice`. `enrich_invoice()` then
assigns a `Category` to each line and corrects OCR damage in the descriptions.
Splitting them means each prompt does one job, and each raw response can be
stored separately.

The split also buys a safety property. The enrichment call is sent only
`position` and `description` per row — never `quantity`, `unit_price`, or
`amount`. Its response schema (`EnrichmentResponse` in `app/domain/invoice.py`)
has no numeric fields at all, so the model is structurally unable to return a
figure. Every number on the resulting `EnrichedLineItem` is copied from the
original `LineItem` in Python, matched by `position`; if a position is missing
from the response the call raises rather than silently producing a short
invoice. Amounts that survived validation cannot be altered by a model that was
never shown them.

`description_raw` keeps the pre-correction text so the correction stays
auditable. It is populated from the original `LineItem.description`, not from
the response — taking it from the response would make it a copy of the corrected
string and the field would carry no information.

### Validation flags, it does not reject

`validate_invoice()` in `app/services/validation.py` returns a `ValidationResult`
and never raises. Findings carry one of two severities:

- `ERROR` — the data contradicts itself: no line items, or
  `quantity x unit_price` does not match the stated `amount`, or the line
  amounts do not sum to the subtotal, or `subtotal + tax` does not match the
  total.
- `WARNING` — missing or unusual but still usable: an absent VAT number, a
  currency outside the known set, a non-positive quantity.

This is the only check that catches the failure mode described under Known
Limitations. Pydantic confirms that a `Decimal` is a `Decimal`; it cannot know
that `54.50` should have been `£4.50`. Those values are individually well-formed
and collectively wrong, and reconciling the arithmetic is the only thing that
makes the contradiction visible.

Errors mark the invoice `INCONSISTENT`; they do not drop it. See Design
decisions for why.

### Storage: the ORM does not leave `app/db/`

`ReceiptRepository` takes and returns Pydantic models from `app/domain/`, never
SQLAlchemy rows. `_to_domain()` is the single crossing point. The pipeline
therefore never holds a session-bound object and cannot trip over a lazy load
after the session closes.

Nothing in the repository commits — it only flushes. `session_scope()` in
`app/db/session.py` owns the transaction boundary, so one upload is one
transaction: if report generation fails, the receipt, its line items and both
LLM records roll back together rather than leaving a row pointing at a file
that was never written.

Three tables. `receipts` holds the invoice fields plus what processing added:
which branch extracted it, what validation concluded (status, and the findings
themselves as `JSONB`), the source filename, the content hash, and the report
path. `line_items` and `llm_calls` hang off it with `ON DELETE CASCADE`.

`file_hash` is unique and indexed. That single constraint is what makes the
deduplication check cheap and what makes a double upload impossible to store
twice even under a race.

`llm_calls` keeps one row per LLM call: the provider's untouched response
envelope as `JSONB`, the model actually served, token counts, and the duration.
The task asks for the raw response *and* the parsed result; the parsed result
is the `receipts` row, and this is the other half. Storing them separately is
why `extract_invoice()` and `enrich_invoice()` each return a pair.

### The report

`generate_report()` takes an `EnrichedInvoice` and a directory and returns the
path it wrote. It knows nothing about the database — which is why the filename
is passed in by the pipeline rather than derived from the invoice. Two
different files can carry the same invoice number, and the bundled `7.pdf` and
`8.pdf` are exactly that case: naming from the invoice alone made the second
report silently overwrite the first. The pipeline names it after the receipt
id, so a report maps one-to-one onto a row.

Category totals are summed in Python, in the generator. The amounts have
already been through `validate_invoice()` by then, so this is arithmetic over
settled numbers — asking a model to add a column would put a checked figure
back at risk for nothing.

The prose summary is the model's only contribution to that page, and the
enrichment prompt forbids it from stating any figure: no amounts, no totals, no
percentages, no counts. It was never shown the prices. The numbers on the page
all come from the table above it, so the two cannot contradict each other.

## Design decisions

Each of these had a workable alternative that was rejected on purpose.

**Over-long documents are rejected, not truncated.** `MAX_PAGES = 10` in
`app/extraction/validation.py` refuses an 11-page file rather than reading the
first ten pages. Truncation is the friendlier behaviour and the wrong one here:
ten pages of a two-hundred-page invoice still yields a `TOTAL`, and it is
confidently wrong in a way nothing downstream can detect. The cost is that a
legitimately long invoice cannot be processed at all. The limit lives only in
`validation.py` so there is one page policy rather than two.

**EasyOCR locally, rather than a vision model.** The scanned branch runs OCR in
the container instead of sending a rasterised page to a multimodal API. A vision
model would almost certainly read `£4.50` correctly where EasyOCR returns
`54.50`, and it would strip 757 MB of torch and 94 MB of OCR weights out of the
image along with the 10-20 minute first build. It was rejected because it
makes the OCR path depend on the network and the reviewer's API budget for every
scanned page, and because the resulting failure mode is worse: a vision model
that misreads a figure produces no signal, whereas EasyOCR's corruption is
caught by the arithmetic check. The image size and the build time are the price.

**Validation flags, and something else decides.** `validate_invoice()` returns
findings and never raises, so an invoice whose arithmetic does not reconcile is
marked `INCONSISTENT` and still passed on. Rejecting outright would be simpler,
but a flagged row in the report is visible to a person while a rejected one is
silent, and the whole point of the arithmetic check is to make a specific
corruption visible.

The pipeline answers the question the check leaves open: an `INCONSISTENT`
invoice **is** stored, but the enrichment call is skipped. Validation runs
before enrichment precisely so that a document whose arithmetic does not
reconcile never reaches the second, billable call. Its line items are stored
uncategorised — `Other`, with `description_raw` equal to `description` — which
is literally true, since nothing categorised them and no correction was
applied.

**Category totals are computed in Python, not asked of the model.** By the time
the report is generated the amounts have been validated, and language models
are unreliable at arithmetic, so summing them in the model would put a checked
number back at risk for no gain. This is why `enrich_invoice()` returns
categories and prose but no figures at all.

**PostgreSQL rather than SQLite.** `docker-compose.yaml` runs a real database
service the application connects to over the network. SQLite would need no
service at all, which is precisely what makes it the weaker demonstration of a
multi-service deployment. The cost is a healthcheck and a startup dependency
before the app can serve anything. It also buys `JSONB`, which is what lets the
raw LLM responses and the validation findings be stored as documents and still
be queried — `raw_response->'usage'->>'prompt_tokens'` works.

**Handlers are `def`, not `async def`.** Processing an invoice blocks for up to
36 seconds on OCR and two LLM round-trips. FastAPI runs a sync handler in a
threadpool, so one upload does not stall the event loop; an `async def` here
would do exactly that and freeze every other request for the duration.

**The schema is created with `create_all()`, not migrations.** It runs on
startup and is idempotent, so `docker compose up` on an empty volume produces a
working database with no extra step. The limit is real and was hit during
development: `create_all()` creates missing tables but never alters existing
ones, so adding the `summary` column to a live database took a manual
`ALTER TABLE`. A second schema change would need the same. Alembic is the
answer past this point; for a fixed schema shipped once, it is ceremony.

**pdfminer for input validation, not pdfplumber.** `validation.py` parses the
document structure with pdfminer even though pdfplumber is already imported
elsewhere. Only pdfminer distinguishes an encrypted PDF from a corrupt one,
which is the difference between `EncryptedPDFError` and `InvalidPDFError` and
therefore between two different messages to the caller. It costs nothing:
pdfminer is already a pdfplumber dependency.

## Verified behaviour

### The test suite

```bash
pip install -r requirements-dev.txt
python -m pytest
```

16 passed, around 50 seconds — most of it the one test that runs EasyOCR for
real. `python -m pytest -m "not slow"` skips it and finishes in about 8.

The suite runs on the host, not in the container: `requirements-dev.txt` is
deliberately separate from `requirements.txt` so the image stays free of test
dependencies. The reviewer runs `docker compose up`, not the tests.

Fixtures live in `conftest.py` at the repository root, not in `test/`. With
pytest's `prepend` import mode the directory of the topmost `conftest.py` goes
on `sys.path`, which is what makes `from app...` work without path hacks. The
encrypted and multi-page PDFs are built at run time, so no binary fixtures are
committed.

What the suite covers:

- Both branches end to end: `7.pdf` through the text layer, `7_scanned.pdf`
  through OCR, each asserting the branch taken and known strings in the output.
- Encrypted PDFs raise `EncryptedPDFError`, not a pdfminer exception.
- The page limit rejects an 11-page document and accepts 10, and bites before
  rasterisation rather than after.
- OCR line grouping, on synthetic bounding boxes, so it runs without EasyOCR.
- The threshold, three ways: every sample lands on its expected side of it, the
  constant sits inside the measured gap with margin, and the comparison is
  inclusive at exactly 100 characters. Without those three the constant could
  have been any value from 1 to 1961 with the suite still green.

`test_sample_lands_on_the_expected_side_of_the_threshold` is parametrised over
`samples/*.pdf` with the scanned ones listed explicitly, so adding a sample adds
a test case automatically and a scanned addition fails until it is declared.

### The end-to-end run

Verified by hand against a live model and a live database, not by the suite.
`7.pdf` and `8.pdf` are the same invoice — OfficePro Supplies, `OPS-8847` — one
digital-born and one a scanned copy, so they take different branches.
`7_scanned.pdf` is a third copy, rasterised from `7.pdf` and rotated slightly.

Both were uploaded through `POST /api/receipts` and produced **identical
structured output**:

| | `7.pdf` | `8.pdf` |
| --- | --- | --- |
| Branch | `text_layer` | `ocr` |
| Line items | 9 | 9 |
| Subtotal / tax / total | 707.90 / 141.58 / 849.48 | 707.90 / 141.58 / 849.48 |
| Currency | GBP | GBP |
| Validation | `CLEAN`, zero issues | `CLEAN`, zero issues |

The scanned copy reaches the same figures as the digital one despite the OCR
corruption documented below — it reads `Currency: €` and `84.50` where the
document says `£` and `£4.50`. That is the case the extraction prompt and the
arithmetic check exist to handle, and it is the single most load-bearing result
here.

Re-uploading a processed file returned the existing receipt in 0.03 seconds
with no LLM call. Both `llm_calls` rows carried a real response envelope with
`finish_reason`, token counts and the unparsed content string. The generated
reports were read back with pdfplumber to confirm the totals on the page match
the database.

Error paths, over HTTP: a non-PDF returns `400 invalid_pdf` naming the uploaded
file, an unknown id `404`, a malformed uuid `422`. A filename of
`../../../etc/evil.pdf` was reduced to `evil.pdf` and stayed inside the
temporary directory.

**Not verified — the honest gap.** Everything above is a hand-run, not a test.
The suite covers the extraction layer only. Nothing automated covers
`extract_invoice()`, `enrich_invoice()`, `validate_invoice()`, the repository,
the pipeline or the API, so a regression in either prompt, in the ORM mapping,
or in a route would go unnoticed until someone runs a document through by hand.

That gap has already cost something once: `LLMCall` was missing the reverse
relationship for `Receipt.llm_calls`, and because SQLAlchemy configures mappers
lazily, it surfaced only on the first real write — not in any test. It is fixed;
the point is that the suite could not have caught it.

`test/test_llm.py` was deleted in `ecc8070` and nothing replaced it. A live-model
test is awkward to justify in a suite the reviewer may run without a key, but
the repository and pipeline could be covered against a test database with
stubbed LLM calls, and are not.

## Known limitations

**Currency symbols become digits in the OCR branch.** EasyOCR reads `£` as `5`,
`8`, `9` or `€`, and it does so on the lowest-confidence fragments. Every row
below is an observed value from `samples/7_scanned.pdf`, not an extrapolation:

| Original | OCR output | Field |
| --- | --- | --- |
| `£4.50` | `54.50` | unit price |
| `£18.90` | `518.90` | unit price |
| `£112.00` | `8112.00` | line amount |
| `£707.90` | `5707.90` | subtotal |
| `Currency: £` | `Currency: €` | document currency |

A corrupted leading digit moves the value by an order of magnitude. Raising the
confidence floor cannot help: the lowest surviving fragment scores 0.308 against
a 0.3 threshold, so a higher floor discards real prices before it discards
errors.

**The amounts are handled; the currency label is not.** The extraction prompt
recovers the figures and the arithmetic check confirms them — both scanned
samples store 707.90 / 141.58 / 849.48, exactly matching the digital original.
But `7_scanned.pdf` ends up recorded as `EUR` rather than `GBP`, because on that
scan EasyOCR replaced `£` with `€` on nearly every line, so the model saw
consistent and overwhelming evidence for the wrong currency. `8.pdf` is a
different scan of the same invoice where the corruption fell differently, and
it resolves correctly.

Nothing downstream can catch this. The arithmetic reconciles perfectly, because
every figure is right and only the label is wrong — a validation rule cannot
distinguish 849.48 EUR from 849.48 GBP. Cross-checking the currency against the
`GB` prefix on the VAT numbers would catch this specific case, and is the
obvious next step.

**The two-column header merges in the OCR branch.** On a skewed scan the issuer
block on the left and the invoice metadata on the right fall inside the same
line-grouping tolerance and come out as single lines:

```
118 Market Street; Manchester, М1 2WD, UK Invoice #: OPS-8847
VATIID: GB456789123 Date: August 10,2026
```

(Verbatim from `7_scanned.pdf`; the mangled punctuation and `VATIID` are the
same OCR pass, not typos here.)

The tolerance that does this is the same one that correctly keeps table rows
apart. It is squeezed between 13px, below which columns merge, and 36px, above
which rows split — so moving it does not solve the problem; column detection
would. Left as is: the model separates issuer from receiver reliably from the
merged text, while changing the tolerance risks the row grouping that works.

**Line items appear twice in the text-layer branch.** On invoices where
pdfplumber detects a table (`6.pdf`, `7.pdf`) the rows show up once in the page
text and again in the `--- TABLE ---` block. Both have eight or more rows, so the
risk of doubled positions in the model's output is real. Fixable with
`page.filter()` over the bounding boxes from `find_tables()`.

**Row numbers are missing in the OCR branch.** Thin single digits in the `#`
column are never emitted by EasyOCR at all, so no confidence threshold could
have recovered them. Which rows are lost varies by scan: `7_scanned.pdf` drops
1, 4, 6, 7 and 9, while `8.pdf` drops 1, 4, 5 and 7 from the same underlying
invoice. The extraction prompt therefore numbers positions itself and ignores
that column.

**No automated coverage past the extraction layer.** The suite tests
extraction only. The pipeline, the repository, the API and both prompts are
verified by hand. See "Verified behaviour" for what that has already cost.

**The schema cannot evolve without manual SQL.** `create_all()` does not alter
existing tables, so a schema change on a database that already has data needs
an `ALTER TABLE` by hand. A fresh volume is unaffected.

**European number formatting is unverified.** The prompt handles `1.234,56` and
`1,234.56`, but no bundled sample uses the European convention, so that branch of
the prompt has never met a real document.

**The `MIN_CONFIDENCE` threshold cannot be patched in tests.** It is bound as a
default argument in `to_lines(..., min_confidence: float = MIN_CONFIDENCE)`, so
patching the module attribute does nothing. Passing the value explicitly still
works. If it ever needs to be configurable, that signature is the place.

## Samples

Nine files, `samples/1.pdf` through `samples/8.pdf` plus `7_scanned.pdf`. All are
single-page.

### What each one actually produces

Every sample below was uploaded through `POST /api/receipts` against a live
model and an empty database. **All nine were accepted, stored and given a
report** — nothing is rejected for being incomplete. What differs is how much
of the invoice was there to find.

The task's minimum is invoice number, date, issuer name and ID, receiver name
and ID, at least eight line items with description/quantity/unit price/amount,
total, and currency. Only four samples clear that bar:

| File | Branch | Status | Items | Meets the 8-item minimum | What is missing or wrong |
| --- | --- | --- | --- | --- | --- |
| `6.pdf` | text layer | `clean` | 8 | yes | nothing |
| `7.pdf` | text layer | `clean` | 9 | yes | nothing |
| `8.pdf` | OCR | `clean` | 9 | yes | nothing |
| `7_scanned.pdf` | OCR | `clean` | 9 | yes | currency stored as `EUR`, should be `GBP` |
| `1.pdf` | text layer | `flagged` | 3 | no | issuer ID, receiver ID, subtotal, tax |
| `2.pdf` | text layer | `inconsistent` | 1 | no | issuer ID, receiver ID, tax; line arithmetic and total do not reconcile |
| `3.pdf` | text layer | `inconsistent` | 1 | no | issuer ID, receiver ID, tax; subtotal 200.00 against a total of 8193.00 |
| `4.pdf` | text layer | `inconsistent` | 0 | no | no line items at all, plus both IDs, subtotal and tax |
| `5.pdf` | text layer | `inconsistent` | 0 | no | no line items at all, plus both IDs, subtotal and tax |

**The four clean ones are the demonstration.** `6.pdf`, `7.pdf` and `8.pdf`
produce a fully populated receipt: every required field present, arithmetic
reconciling, a category on every line, a summary, and a report. `7.pdf` and
`8.pdf` are the same invoice digital-born and scanned, and reach identical
figures through different branches.

**`1.pdf` through `5.pdf` are thin documents, not failures of the pipeline.**
They were collected as layout variety rather than as complete invoices —
`4.pdf` and `5.pdf` are service-details forms with no line-item table for
anything to find, and `3.pdf` is filler text with a subtotal that has no
relationship to its total. The pipeline reports exactly that: `no_line_items`,
`total_mismatch`, `missing_issuer_id`. They are stored with those findings
attached rather than silently dropped, which is the whole point of validation
flagging instead of rejecting.

Note what the status buys. All five imperfect samples cost **one** LLM call
each, not two: an `inconsistent` invoice never reaches enrichment, so it has no
categories and no summary. `1.pdf` is only `flagged` — warnings, no
contradictions — so it was enriched normally.

**The one genuine defect visible here is `7_scanned.pdf`'s currency.** Its
amounts are all correct (707.90 / 141.58 / 849.48, identical to the digital
twin), but the currency is stored as `EUR`. EasyOCR turned `£` into `€` on
nearly every line of that scan — `€6.40`, `€141.58`, `€849.48` — so the model
had overwhelming and consistent evidence for the wrong answer, and the `GB`
VAT prefixes were not enough to outweigh it. `8.pdf` is a different scan of the
same invoice where the corruption fell differently, and it resolves to `GBP`
correctly. Nothing downstream can catch this: the arithmetic reconciles
perfectly, because every figure is right and only the label is wrong.

| File | Content | Branch |
| --- | --- | --- |
| `1.pdf` | WeasyPrint specimen invoice, #12345, one detected table | text layer |
| `2.pdf` | SuperStore invoice #30118, separate billing and shipping addresses | text layer |
| `3.pdf` | Service details form `UB359948`, two detected tables | text layer |
| `4.pdf` | Service details form, ABC Trading, three detected tables | text layer |
| `5.pdf` | Service details form `INVO-007`, two detected tables | text layer |
| `6.pdf` | DevSync Solutions, Sofia; Bulgarian VAT number but `Currency: $` — the currency ambiguity the prompt has to resolve from evidence rather than the symbol | text layer |
| `7.pdf` | OfficePro Supplies `OPS-8847`, nine line items, GBP; also the clearest case of the duplicated-table-rows problem | text layer |
| `7_scanned.pdf` | `7.pdf` rasterised and slightly rotated. The only sample with a digital twin, so OCR output can be diffed against exact text | OCR |
| `8.pdf` | An independent scanned copy of the same `OPS-8847` invoice | OCR |
