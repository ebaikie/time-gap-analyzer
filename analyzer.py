"""Local OCR + time-gap analysis. No external API, fully on-box."""
import re
from PIL import Image
import pytesseract

TIME_RE = re.compile(r'^([01]?\d|2[0-3]):[0-5]\d$')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
OCR_CONFIG = '--psm 6 -c tessedit_char_whitelist=0123456789:-'


# ---------- image prep ----------
def _otsu_threshold(gray):
    hist = gray.histogram()
    total = sum(hist)
    sum_all = sum(i * hist[i] for i in range(256))
    sumB = wB = 0
    best_var = 0.0
    thresh = 128
    for i in range(256):
        wB += hist[i]
        if wB == 0:
            continue
        wF = total - wB
        if wF == 0:
            break
        sumB += i * hist[i]
        mB = sumB / wB
        mF = (sum_all - sumB) / wF
        between = wB * wF * (mB - mF) ** 2
        if between > best_var:
            best_var = between
            thresh = i
    return thresh


def preprocess(img):
    """Grayscale -> adaptive upscale (~2800px wide) -> Otsu binarize."""
    gray = img.convert('L')
    w, h = gray.size
    scale = max(1, min(5, round(2800 / w))) if w else 3
    gray = gray.resize((w * scale, h * scale))
    t = _otsu_threshold(gray)
    return gray.point(lambda p: 0 if p < t else 255)


# ---------- OCR + layout ----------
def _ocr_tokens(img):
    d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT,
                                  config=OCR_CONFIG, timeout=60)
    toks = []
    for i in range(len(d['text'])):
        txt = d['text'][i].strip()
        if not txt:
            continue
        toks.append({
            'text': txt,
            'cx': d['left'][i] + d['width'][i] / 2,
            'cy': d['top'][i] + d['height'][i] / 2,
            'h': d['height'][i],
        })
    return toks


def _cluster_rows(toks):
    """Group tokens into rows by vertical position (layout-independent)."""
    if not toks:
        return []
    heights = sorted(t['h'] for t in toks)
    med_h = heights[len(heights) // 2]
    thresh = max(med_h * 0.7, 8)
    toks = sorted(toks, key=lambda t: t['cy'])
    rows, cur = [], [toks[0]]
    for t in toks[1:]:
        if abs(t['cy'] - cur[-1]['cy']) <= thresh:
            cur.append(t)
        else:
            rows.append(cur)
            cur = [t]
    rows.append(cur)
    return rows


def _normalize_time(tok):
    t = tok.replace('.', ':').replace(';', ':')
    if re.fullmatch(r'\d{4}', t):       # 0800 -> 08:00
        t = t[:2] + ':' + t[2:]
    if TIME_RE.match(t):
        return t
    return None


def extract_entries(img):
    """Return (date, entries, warnings). Times stored as 'HHMM'."""
    rows = _cluster_rows(_ocr_tokens(preprocess(img)))
    entries, warnings, date = [], [], None
    for idx, row in enumerate(rows):
        row = sorted(row, key=lambda t: t['cx'])
        times = []
        for t in row:
            nt = _normalize_time(t['text'])
            if nt:
                times.append(nt)
            elif DATE_RE.match(t['text']) and not date:
                date = t['text']
        if len(times) >= 2:
            entries.append({'start': times[0].replace(':', ''),
                            'end': times[1].replace(':', '')})
        elif len(times) == 1:
            warnings.append(f"Row near {times[0]} has only one readable time — please verify.")
    return date, entries, warnings


# ---------- validation ----------
def _to_min(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[2:])


def validate_entries(entries):
    """Flag rows that are logically impossible or oddly formatted."""
    warnings = []
    # Detect dominant zero-padding (these forms pad to 2-digit hours)
    padded = sum(1 for e in entries for v in (e['start'], e['end'])
                 if len(v) == 4 and v[0] == '0') 
    for e in entries:
        s, en = e['start'], e['end']
        sd = f"{s[:2]}:{s[2:]}"
        ed = f"{en[:2]}:{en[2:]}"
        if _to_min(en) <= _to_min(s):
            warnings.append(f"Row {sd}-{ed}: end is not after start — likely a misread, please verify.")
    return warnings


# ---------- gap + overlap analysis (pure logic, unchanged) ----------
def _fmt(hhmm):
    return f"{hhmm[:2]}:{hhmm[2:]}"


def _min_to_hhmm(m):
    return f"{m // 60:02d}{m % 60:02d}"


def _fmt_dur(m):
    h, mm = m // 60, m % 60
    return f"{h}h {mm}m" if h else f"{mm}m"


def analyze(entries, required_start='0800', min_logged_minutes=510):
    if not entries:
        return None
    se = sorted(entries, key=lambda x: _to_min(x['start']))
    gaps, overlaps = [], []
    total = 0
    coverage_end = None
    for e in se:
        s, en = _to_min(e['start']), _to_min(e['end'])
        total += max(0, en - s)
        if coverage_end is None:
            coverage_end = en
            continue
        if s > coverage_end:
            gaps.append({'start': _fmt(_min_to_hhmm(coverage_end)),
                         'end': _fmt(e['start']),
                         'duration_minutes': s - coverage_end,
                         'duration_display': _fmt_dur(s - coverage_end)})
            coverage_end = en
        else:
            if s < coverage_end:
                ov = min(coverage_end, en) - s
                overlaps.append({'at': _fmt(e['start']),
                                 'duration_minutes': ov,
                                 'duration_display': _fmt_dur(ov)})
            coverage_end = max(coverage_end, en)
    elapsed = coverage_end - _to_min(se[0]['start'])
    return {
        'entries': se,
        'gaps': gaps,
        'overlaps': overlaps,
        'total_minutes': total,
        'total_display': f"{total // 60}h {total % 60}m",
        'elapsed_minutes': elapsed,
        'elapsed_display': _fmt_dur(elapsed),
        'gap_count': len(gaps),
        'overlap_count': len(overlaps),
        'requirement_issues': check_requirements(se, total, required_start, min_logged_minutes),
    }


# ---------- requirements ----------

def check_requirements(sorted_entries, total_minutes, required_start='0800', min_logged_minutes=510):
    """Check start-time and minimum-hours requirements."""
    issues = []
    if not sorted_entries:
        return issues

    first = sorted_entries[0]['start']
    if _to_min(first) > _to_min(required_start):
        late = _to_min(first) - _to_min(required_start)
        req_fmt = f"{required_start[:2]}:{required_start[2:]}"
        issues.append({
            'type':    'late_start',
            'message': f'Started at {_fmt(first)}, expected by {req_fmt}',
            'detail':  f'{_fmt_dur(late)} late',
        })

    if total_minutes < min_logged_minutes:
        short = min_logged_minutes - total_minutes
        need_fmt = _fmt_dur(min_logged_minutes)
        issues.append({
            'type':    'short_hours',
            'message': f'Only {_fmt_dur(total_minutes)} logged, need {need_fmt}',
            'detail':  f'{_fmt_dur(short)} short',
        })

    return issues
