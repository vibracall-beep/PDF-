"""Conservative Markdown semantics, with inert literal text and bounded link syntax.

PDFs do not necessarily contain semantic lists. Infer them only from explicit
markers and nearby aligned geometry; uncertain source text remains literal.
"""
from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import quote, unquote, urlsplit

import fitz


def escape_text(value):
    text = html.escape(str(value or ''), quote=False).replace('\\', '\\\\')
    return re.sub(r'([`*_{}\[\]#!|])', r'\\\1', text)


def inert_line(value):
    # These block markers are not handled by ordinary inline escaping.
    value = re.sub(r'^(\s*)([-+])(?=\s|$)', r'\1\\\2', value)
    value = re.sub(r'^(\s*\d{1,9})([.)])(?=\s|$)', r'\1\\\2', value)
    if re.fullmatch(r'\s*[-=]{3,}\s*', value):
        value = value.replace('-', '\\-').replace('=', '\\=')
    return value


def safe_uri(value):
    """Return a CommonMark angle destination, never a new source instruction."""
    if not isinstance(value, str) or not value or len(value) > 8192:
        return None
    if any(unicodedata.category(character) in ('Cc', 'Cf', 'Cs') for character in value):
        return None
    decoded = unquote(value)
    if any(unicodedata.category(character) in ('Cc', 'Cf', 'Cs') for character in decoded):
        return None
    if '\\' in value or '\\' in decoded:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ('https', 'http', 'mailto'):
            return None
        if parsed.scheme.lower() in ('https', 'http'):
            if not parsed.hostname or any(character.isspace() for character in parsed.netloc):
                return None
            _ = parsed.port  # Malformed ports/brackets are not valid destinations.
        elif not parsed.path or parsed.netloc:
            return None
    except ValueError:
        return None
    # Preserve literal ampersands through CommonMark's entity decoding. Encode
    # Markdown delimiters, whitespace and non-ASCII URI bytes explicitly.
    normalized = re.sub(r'%(?![0-9a-fA-F]{2})', '%25', value)
    normalized = quote(normalized, safe=":/?#@!$&'*+,;=%-._~")
    return '<' + normalized.replace('&', '&amp;') + '>'


def page_links(page, selected_pages):
    result = []
    for source in page.get_links():
        target = safe_uri(source.get('uri'))
        if source.get('kind') == fitz.LINK_GOTO:
            page_number = source.get('page')
            if isinstance(page_number, int) and page_number in selected_pages:
                target = f'<#pdf-page-{page_number + 1}>'
        if target is None:
            continue
        area = fitz.Rect(source['from'])
        if area.is_empty or area.is_infinite:
            continue
        label = page.get_textbox(area).strip()
        result.append({'rect': area, 'target': target, 'label': label or 'Link', 'used': False})
    return result


def styled_slice(line, start=0, stop=None):
    text = ''.join(span['text'] for span in line['spans'])
    stop = len(text) if stop is None else stop
    pieces = []
    offset = 0
    for span in line['spans']:
        end = offset + len(span['text'])
        left, right = max(start, offset), min(stop, end)
        if left < right:
            value = escape_text(span['text'][left - offset:right - offset])
            marker = '***' if span.get('flags', 0) & 18 == 18 else '**' if span.get('flags', 0) & 16 else '*' if span.get('flags', 0) & 2 else ''
            # Emphasis delimiters cannot enclose leading/trailing whitespace.
            plain = value.strip()
            if marker and plain:
                before = value[:len(value) - len(value.lstrip())]
                after = value[len(value.rstrip()):]
                value = before + marker + plain + marker + after
            pieces.append(value)
        offset = end
    return ''.join(pieces)


def linked_line(line, links, start=0):
    text = ''.join(span['text'] for span in line['spans'])
    ranges = []
    for link in links:
        if link['used'] or not fitz.Rect(line['bbox']).intersects(link['rect']):
            continue
        label = link['label']
        # Only map a unique, single-line annotation label; uncertain multi-line
        # or overlapping annotations remain explicit links after the page.
        if '\n' in label or not label or text.count(label) != 1:
            continue
        position = text.find(label)
        if position < start:
            continue
        ranges.append((position, position + len(label), link))
    ranges.sort(key=lambda entry: (entry[0], entry[1]))
    if any(current[0] < previous[1] for previous, current in zip(ranges, ranges[1:])):
        return styled_slice(line, start)
    parts = []
    offset = start
    for left, right, link in ranges:
        parts.append(styled_slice(line, offset, left))
        parts.append('[' + styled_slice(line, left, right) + '](' + link['target'] + ')')
        link['used'] = True
        offset = right
    parts.append(styled_slice(line, offset))
    return ''.join(parts)


_MARKER = re.compile(r'^(\s*)(?:(?P<bullet>[•◦▪▫‣⁃·*+\-])|(?P<number>\d{1,3})(?P<delimiter>[.)]))[ \t]+(?=\S)')
_STRONG = set('•◦▪▫‣⁃')


def list_plan(items):
    """Map visible markers to lists only when their sequence/geometry agrees."""
    runs = []
    active = []
    previous = None
    for block_index, block in enumerate(items):
        if block['type'] != 0:
            if active: runs.append(active)
            active = []; previous = None
            continue
        for line_index, line in enumerate(block['lines']):
            text = ''.join(span['text'] for span in line['spans'])
            match = _MARKER.match(text)
            rect = fitz.Rect(line['bbox'])
            if match is None:
                if active: runs.append(active)
                active = []; previous = None
                continue
            size = max(float(span.get('size', 11)) for span in line['spans'])
            if previous is not None and (rect.y0 <= previous.y0 + 1 or rect.y0 - previous.y1 > max(42, size * 2) or abs(rect.x0 - previous.x0) > 72):
                if active: runs.append(active)
                active = []
            entry = {'key': (block_index, line_index), 'rect': rect, 'match': match}
            active.append(entry); previous = rect
    if active: runs.append(active)
    plan = {}
    for run in runs:
        # Build aligned peer groups once. A scanned page may have thousands of
        # lines; do not rescan the entire run for each candidate.
        groups = []
        for item in sorted(run, key=lambda entry: entry['rect'].x0):
            if not groups or item['rect'].x0 - groups[-1][0]['rect'].x0 > 3:
                groups.append([])
            groups[-1].append(item)
        proven_keys = set()
        bullet_counts = {}
        for item in run:
            bullet = item['match']['bullet']
            if bullet: bullet_counts[bullet] = bullet_counts.get(bullet, 0) + 1
        for group in groups:
            for delimiter in ('.', ')'):
                peers = sorted((item for item in group if item['match']['number'] is not None and item['match']['delimiter'] == delimiter), key=lambda item: item['rect'].y0)
                numbers = [item['match']['number'] for item in peers]
                if len(numbers) >= 2 and all(value == str(int(value)) for value in numbers) and all(int(after) == int(before) + 1 for before, after in zip(numbers, numbers[1:])):
                    proven_keys.update(item['key'] for item in peers)
        levels = []
        for item in run:
            match = item['match']; x = item['rect'].x0
            proven = item['key'] in proven_keys if match['number'] is not None else match['bullet'] in _STRONG or bullet_counts[match['bullet']] >= 2
            if not proven:
                levels = []
                continue
            if not levels:
                levels = [x]
            elif abs(x - levels[-1]) <= 3:
                pass
            elif 8 <= x - levels[-1] <= 72 and len(levels) < 9:
                levels.append(x)
            else:
                found = next((depth for depth, value in enumerate(levels) if abs(value - x) <= 3), None)
                levels = levels[:found + 1] if found is not None else [x]
            prefix = match['number'] + match['delimiter'] + ' ' if match['number'] is not None else '- '
            plan[item['key']] = ('    ' * (len(levels) - 1) + prefix, match.end())
    return plan
