#!/usr/bin/env python3
"""
fetch_selected_conferences.py

The lab's own selected conferences (field "Health" in conference-list.json)
are not in the ccfddl dataset, so their next edition is read from each
conference's official website and written to data/conference-selected.json,
which update_conferences.py merges in.

Websites change, so this is best-effort: when a page cannot be read or no
upcoming date range is found, the previous entry for that conference is kept.

Usage:  python3 scripts/fetch_selected_conferences.py [--debug]
"""
import datetime
import html
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'data', 'conference-selected.json')
DEBUG = '--debug' in sys.argv

# acronym (as in conference-list.json) -> pages to read, in order of preference
SOURCES = {
    'CHIL': ['https://chil.ahli.cc/'],
    'ML4H': ['https://ml4h.ahli.cc/'],
    # AMIA (Amplify, Annual Symposium): amia.org refuses automated requests (HTTP 403),
    # so those two stay hand-entered in conference-overrides.json.
    'HIMSS': ['https://www.himssconference.com/about-the-conference', 'https://www.himssconference.com/'],
}

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
MON = r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?'
DASH = r'\s*(?:-|–|—|to|through)\s*'
# "April 5-8, 2027" | "May 30 - June 3, 2027" | "5-8 April 2027"
PATTERNS = [
    re.compile(rf'{MON}\s+(\d{{1,2}}){DASH}(\d{{1,2}}),?\s+(20\d\d)', re.I),
    re.compile(rf'{MON}\s+(\d{{1,2}}){DASH}{MON}\s+(\d{{1,2}}),?\s+(20\d\d)', re.I),
    re.compile(rf'(\d{{1,2}}){DASH}(\d{{1,2}})\s+{MON},?\s+(20\d\d)', re.I),
]


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,*/*', 'Accept-Language': 'en'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def to_text(page):
    page = re.sub(r'(?is)<(script|style|noscript)\b.*?</\1>', ' ', page)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', page)))


def json_ld_events(page):
    out = []
    for block in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                stack.extend(v for v in d.values() if isinstance(v, (dict, list)))
                if d.get('startDate'):
                    loc = d.get('location') or {}
                    if isinstance(loc, list):
                        loc = loc[0] if loc else {}
                    addr = loc.get('address') if isinstance(loc, dict) else None
                    place = ''
                    if isinstance(addr, dict):
                        place = ', '.join(x for x in (addr.get('addressLocality'), addr.get('addressRegion'), addr.get('addressCountry')) if isinstance(x, str) and x)
                    elif isinstance(addr, str):
                        place = addr
                    out.append((str(d['startDate'])[:10], str(d.get('endDate') or d['startDate'])[:10], place))
    return out


def text_ranges(text):
    """All date ranges in the text, in order of appearance: (pos, start, end, context)."""
    found = []
    for i, rx in enumerate(PATTERNS):
        for m in rx.finditer(text):
            g = m.groups()
            try:
                if i == 0:
                    mo, d1, d2, y = MONTHS[g[0][:3].lower()], int(g[1]), int(g[2]), int(g[3])
                    s, e = datetime.date(y, mo, d1), datetime.date(y, mo, d2)
                elif i == 1:
                    m1, d1, m2, d2, y = MONTHS[g[0][:3].lower()], int(g[1]), MONTHS[g[2][:3].lower()], int(g[3]), int(g[4])
                    s, e = datetime.date(y - 1 if m1 > m2 else y, m1, d1), datetime.date(y, m2, d2)
                else:
                    d1, d2, mo, y = int(g[0]), int(g[1]), MONTHS[g[2][:3].lower()], int(g[3])
                    s, e = datetime.date(y, mo, d1), datetime.date(y, mo, d2)
            except (ValueError, KeyError):
                continue
            if s <= e and (e - s).days <= 10:
                found.append((m.start(), s, e, text[max(0, m.start() - 80):m.end() + 120], m.end()))
    return sorted(found)


COUNTRY = r'(?:[A-Z]{2}\b|United States|United Kingdom|South Korea|New Zealand|[A-Z][a-z]+)'
PLACE = re.compile(rf"([A-Z][A-Za-z.'\-]+(?: [A-Z][A-Za-z.'\-]+){{0,2}}),\s*({COUNTRY})")
US_STATES = set('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split())


def place_after(text, end_pos):
    """'City, Region' named shortly after the date, e.g. '· Chicago, IL'."""
    m = PLACE.search(text[end_pos:end_pos + 90])
    if not m:
        return ''
    city, region = m.group(1), m.group(2)
    return f'{city}, {region}, USA' if region in US_STATES else f'{city}, {region}'


def main():
    today = datetime.date.today()
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except (OSError, ValueError):
        prev = {}
    result = {k: v for k, v in prev.items() if k in SOURCES}

    for name, urls in SOURCES.items():
        print(f'→ {name}')
        for url in urls:
            try:
                page = fetch(url)
            except Exception as e:  # network errors, 403s, ...
                print(f'  ! {url}: {e}')
                continue
            text = to_text(page)
            lds = json_ld_events(page)
            ranges = text_ranges(text)
            print(f'  {url}: {len(page)} bytes, {len(lds)} JSON-LD events, {len(ranges)} date ranges')
            if DEBUG:
                print('    title:', (re.search(r'(?is)<title[^>]*>(.*?)</title>', page) or [None, ''])[1].strip()[:120])
                for ld in lds[:5]:
                    print('    LD', ld)
                for _, s, e, ctx, _ in ranges[:8]:
                    print(f'    {s}..{e} | {ctx!r}')
            # first upcoming date range on the page (deadlines are single dates, so they are not picked up)
            upcoming = [r for r in ranges if r[2] >= today]
            if not upcoming:
                print('  no upcoming date range on this page')
                continue
            _, s, e, _, end_pos = upcoming[0]
            place = next((p for p in (place_after(text, r[4]) for r in upcoming if (r[1], r[2]) == (s, e)) if p), '')
            old = (prev.get(name) or [{}])[0]
            if not place and old.get('start') == s.isoformat():
                place = old.get('place', '')
            result[name] = [{'year': e.year, 'start': s.isoformat(), 'end': e.isoformat(), 'place': place, 'link': url}]
            print(f'  ✓ {s} – {e} | {place or "(place not found)"}')
            break
        else:
            print('  kept previous entry' if name in result else '  nothing found')
    if DEBUG:
        print('(debug run: nothing written)')
        return
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
        f.write('\n')


if __name__ == '__main__':
    main()
