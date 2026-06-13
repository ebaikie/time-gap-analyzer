# Time Gap Analyzer — Deployment Guide

Self-hosted Flask app that reads a screenshot of a time-tracking form and
reports missing time (gaps), overlaps, and total hours. **Fully local** —
OCR runs on-box with Tesseract, no API key, no network calls, nothing leaves
the machine.

## How it works

1. Image is grayscaled, upscaled (~2800px wide), and binarized with an
   adaptive Otsu threshold (adapts to light/dark screenshots).
2. Tesseract OCRs with a digit/colon whitelist (`0123456789:-`).
3. Tokens are clustered into rows by vertical position and columns by
   horizontal position — so it does **not** depend on the data being in the
   same place in every screenshot.
4. Times are validated (must be HH:MM, end after start); anything suspect is
   flagged for you to confirm rather than silently used.
5. Gap + overlap analysis runs on the parsed times.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Flask server (port 5060) |
| `analyzer.py` | OCR + gap/overlap logic (no Flask, unit-testable) |
| `templates/index.html` | Frontend UI |
| `requirements.txt` | Python deps |

## Install on nosy-box

```bash
# 1. System dependency (the OCR engine itself)
sudo apt-get update && sudo apt-get install -y tesseract-ocr

# 2. App directory
mkdir -p ~/Apps/time-gap-analyzer/templates
cd ~/Apps/time-gap-analyzer
# copy app.py, analyzer.py, requirements.txt here
# copy templates_index.html -> templates/index.html

# 3. Python deps
pip install -r requirements.txt --break-system-packages

# 4. Run
python app.py
# visit http://localhost:5060
```

## Persist with PM2

```bash
cd ~/Apps/time-gap-analyzer
pm2 start app.py --name time-gap-analyzer --interpreter python3
pm2 save
```

(No env vars needed — there's no API key.)

## Cloudflare Tunnel

```bash
cloudflared config route add --hostname time-gap-analyzer.ebaikie.com --service http://localhost:5060
```

## Notes

- Tested against real screenshots: correctly finds the 1h 30m gap (12:30–14:00)
  on the June 2 form and confirms June 3 is continuous, including flagging the
  two overlapping rows on June 2.
- Typical analysis time is well under a second per screenshot on a CPU.
- Verify Tesseract version with `tesseract --version` (5.x recommended).
- If a screenshot is very small, OCR accuracy improves with a larger source
  image — the app upscales automatically but a higher-res capture helps.
