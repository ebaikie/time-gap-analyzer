from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import re
from PIL import Image
import io
import urllib.request
import analyzer

EXTENSION_PRIVACY_GIST = (
    'https://gist.githubusercontent.com/ebaikie/'
    '1a18d21a217f5472831445927edc1c9c/raw/gistfile1.txt'
)

EXTENSION_PRIVACY_FALLBACK = """Privacy Policy — Time Gap Analyzer (Browser Extension)
Last updated: 10 June 2026

Summary
Time Gap Analyzer does not collect, store, transmit, or share any personal data. All processing happens entirely on your device.

What the extension does
When you click the extension's toolbar button, it captures a screenshot of the currently visible browser tab, reads the time values shown using an on-device optical character recognition (OCR) engine, and displays a summary of gaps, overlaps, and pay-requirement checks.

Data handling
Screenshots are held in memory only for the moment needed to perform OCR, and are then discarded. They are never saved to disk, transmitted, or sent to any server. Timesheet times read from the screenshot exist only in memory during analysis and are discarded when you close the popup. They are never stored or transmitted. Settings (your required start time and minimum hours) are stored locally in your browser using the standard extension storage API. If you are signed into your browser, these settings may sync across your own devices via your browser account. They are never sent to the developer or any third party.

Network activity
The extension makes one type of network request: on first use, it downloads the open-source Tesseract OCR language model (a binary data file, approximately 4 MB) from the jsDelivr public CDN (cdn.jsdelivr.net). This file is cached by your browser for subsequent use. No personal data, screenshots, or timesheet content is included in this request — it only retrieves a static model file.

Third parties
The extension does not use analytics, advertising, tracking, or any third-party data-collection services.

Data sale and transfer
The developer does not sell or transfer user data to any third party, does not use data for any purpose unrelated to the extension's single function, and does not use data to determine creditworthiness or for lending purposes.

Contact
For questions about this privacy policy, contact: ebaikie@gmail.com"""


def _fetch_extension_privacy():
    """Fetch extension privacy policy from gist; return (text, live)."""
    try:
        with urllib.request.urlopen(EXTENSION_PRIVACY_GIST, timeout=5) as r:
            return r.read().decode('utf-8'), True
    except Exception:
        return EXTENSION_PRIVACY_FALLBACK, False


def _parse_privacy_text(text):
    """Split plain-text policy into (title, updated, sections)."""
    lines = [l.rstrip() for l in text.strip().splitlines()]
    title = lines[0] if lines else 'Privacy Policy'
    updated = ''
    body_lines = []
    for i, line in enumerate(lines[1:], 1):
        if line.lower().startswith('last updated'):
            updated = line
            body_lines = lines[i + 1:]
            break
    else:
        body_lines = lines[1:]

    # Split into paragraphs on blank lines
    paras, current = [], []
    for line in body_lines:
        if line == '':
            if current:
                paras.append('\n'.join(current))
                current = []
        else:
            current.append(line)
    if current:
        paras.append('\n'.join(current))

    # Classify each paragraph: short single-line = heading, else body
    # First body paragraph after a "Summary" heading becomes type 'summary'
    raw = []
    for p in paras:
        if '\n' not in p and len(p) < 60 and not p.endswith('.'):
            raw.append({'type': 'heading', 'text': p})
        else:
            raw.append({'type': 'body', 'text': p})

    sections = []
    prev_summary = False
    for item in raw:
        if item['type'] == 'heading' and item['text'].lower() == 'summary':
            prev_summary = True
            sections.append(item)
        elif prev_summary and item['type'] == 'body':
            sections.append({'type': 'summary', 'text': item['text']})
            prev_summary = False
        else:
            prev_summary = False
            sections.append(item)

    return title, updated, sections


def _parse_hhmm(val, default):
    """Accept HH:MM or HHMM, return HHMM string."""
    if val:
        v = val.strip().replace(':', '')
        if re.fullmatch(r'\d{4}', v):
            return v
    return default


def _parse_min_hours(val, default_minutes):
    """Accept HH:MM duration string, return total minutes."""
    if val:
        m = re.fullmatch(r'(\d{1,2}):(\d{2})', val.strip())
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
    return default_minutes

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024


@app.after_request
def cors(response):
    origin = request.headers.get('Origin', '')
    if origin.startswith('moz-extension://') or origin.startswith('chrome-extension://'):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/extension-privacy')
def extension_privacy():
    text, live = _fetch_extension_privacy()
    title, updated, sections = _parse_privacy_text(text)
    return render_template('extension_privacy.html',
                           title=title, updated=updated,
                           sections=sections, live=live)


@app.route('/example.png')
def example_image():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'example.png')


@app.route('/api/analyze', methods=['POST', 'OPTIONS'])
def analyze_route():
    if request.method == 'OPTIONS':
        return '', 204
    if 'image' not in request.files or request.files['image'].filename == '':
        return jsonify({'error': 'No image provided'}), 400
    file = request.files['image']
    try:
        img = Image.open(io.BytesIO(file.read()))
    except Exception:
        return jsonify({'error': 'Could not read image file'}), 400
    try:
        date, entries, warnings = analyzer.extract_entries(img)
    except RuntimeError as e:
        if 'timeout' in str(e).lower():
            return jsonify({'error': 'OCR timed out — the server is under load, please try again shortly.'}), 503
        raise
    warnings = warnings + analyzer.validate_entries(entries)
    if not entries:
        return jsonify({'error': 'No time entries found in the screenshot.'}), 400
    required_start = _parse_hhmm(request.form.get('required_start'), '0800')
    min_logged_minutes = _parse_min_hours(request.form.get('min_hours'), 510)
    result = analyzer.analyze(entries, required_start, min_logged_minutes)
    return jsonify({
        'date': date or 'Unknown',
        'entries': result['entries'],
        'gaps': result['gaps'],
        'overlaps': result['overlaps'],
        'warnings': warnings,
        'requirement_issues': result['requirement_issues'],
        'total_display': result['total_display'],
        'total_minutes': result['total_minutes'],
        'elapsed_display': result['elapsed_display'],
        'elapsed_minutes': result['elapsed_minutes'],
        'gap_count': result['gap_count'],
        'overlap_count': result['overlap_count'],
        'has_gaps': result['gap_count'] > 0,
    })


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5065)
