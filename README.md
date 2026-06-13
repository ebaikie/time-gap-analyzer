# Time Gap Analyzer

Screenshot OCR → timesheet gap and overlap checker. Upload a screenshot of your time-tracking form and get an instant summary of gaps, overlaps, and pay-requirement checks — all processed locally with no external APIs.

**Live:** https://timegapanalyzer.113374.xyz

## Features

- Detects gaps and overlaps between time entries
- Flags late starts and short-hours against configurable thresholds
- Layout-independent OCR — works on any time-tracking screenshot format
- Fully in-memory: screenshot is never written to disk or sent anywhere external
- Light/dark mode (Pastel/Aurora themes)
- Browser extensions for Chrome and Firefox (see below)

## Stack

- **Backend:** Flask + Tesseract OCR (pytesseract, Pillow)
- **OCR pipeline:** grayscale → upscale to ~2800px → Otsu binarize → Tesseract with digit/colon whitelist
- **Process manager:** PM2

## Browser Extensions

| Browser | Link |
|---------|------|
| Chrome | [Chrome Web Store](https://chromewebstore.google.com/detail/hfiloaakinclbfkfaojjdgfjaciegoab) |
| Firefox | [Firefox Add-ons](https://addons.mozilla.org/en-US/firefox/addon/time-gap-analyzer/) |
| Edge | Pending review |

The extensions run OCR locally in the browser (Tesseract.js) — no server needed.

## Running Locally

```bash
pip install -r requirements.txt
# Tesseract must be installed system-wide
sudo apt install tesseract-ocr   # Debian/Ubuntu
python app.py
```

Runs on port 5065 by default.

## Privacy

All processing is server-side and in-memory. No data is stored or transmitted to third parties. See [/privacy](/privacy) for the full policy.
