# Docling First OCR Migration Runbook

## Goal
Move PDF ingestion to `Docling first` with safe `Yandex fallback` during transition.

## Feature Flags
Set in `.env`:

- `PDF_OCR_PRIMARY_ENGINE=docling` (`docling|yandex`)
- `PDF_OCR_ENABLE_YANDEX_FALLBACK=true`
- `PDF_OCR_ENABLE_PYPDF_FALLBACK=true`
- `PDF_OCR_ENABLE_TESSERACT_FALLBACK=true`
- `PDF_OCR_PREFER_YANDEX=false` (legacy compatibility switch)

## Rollout Stages
1. **Dev/Staging**: Enable `docling` primary and validate logs/quality.
2. **Limited Production**: Re-upload a subset of legal corpus PDFs (key codes).
3. **Full Production**: Keep Yandex only as fallback.

## Rollback
Single env change:

- `PDF_OCR_PRIMARY_ENGINE=yandex`

No code rollback required.

## Re-upload for Legal Corpus
To get Docling-based chunks for legal corpus:

1. Upload updated PDF codes again in Legal Corpus UI.
2. Verify answers with citations.
3. Gradually replace legacy entries; do not purge all old files at once.

## Smoke Checklist
- PDF scan: extraction succeeds, citations appear.
- Text PDF: no quality regression in article references.
- Fallback scenario: Docling failure still returns results through Yandex/PyPDF.
- Logs contain selected engine, fallback reason, pages/chars extracted.
