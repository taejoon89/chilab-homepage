#!/usr/bin/env python3
"""
update_conferences.py

Build data/conferences.json, which the Conferences page reads: for each
conference in data/conference-list.json (the KIISE 2024 list plus the
lab's own selected conferences, field "Health"), the next
edition's dates and place.

Sources, in order:
  1. data/conference-overrides.json  - editions entered by hand
  2. ccfddl/ccf-deadlines            - community-maintained dataset (MIT),
                                       https://github.com/ccfddl/ccf-deadlines

Usage:
  git clone --depth 1 https://github.com/ccfddl/ccf-deadlines /tmp/ccfddl
  python3 scripts/update_conferences.py /tmp/ccfddl

Runs weekly via .github/workflows/update-conferences.yml. Requires PyYAML.
"""
import datetime
import glob
import json
import os
import re
import sys

import yaml

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
LIST = os.path.join(ROOT, 'data', 'conference-list.json')
OVERRIDES = os.path.join(ROOT, 'data', 'conference-overrides.json')
OUT = os.path.join(ROOT, 'data', 'conferences.json')

# Our acronym -> title used in the ccfddl dataset, where they differ.
ALIAS = {
    'KDD': 'sigkdd', 'SIGGRAPH': 'acm siggraph', 'SIGGRAPH ASIA': 'acm siggraph asia',
    'UBICOMP': 'ubicomp/iswc', 'USENIX ATC': 'sigops atc', 'USENIX FAST': 'fast',
    'USENIX NSDI': 'nsdi', 'USENIX OSDI': 'osdi', 'VIS': 'ieee vis', 'VR': 'ieee vr',
    'CGO': 'ieee/acm cgo', 'CSF': 'csfw', 'EG': 'eurographics', 'MM': 'acm mm',
    'PKDD': 'ecml-pkdd',
}
# Acronym clashes: the dataset entry with this title is a different conference.
# (tier-A "FSE" on our list is Fast Software Encryption, not the SE conference.)
NO_DATASET = {('FSE', 'A')}

MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}


def norm(s):
    return re.sub(r'[^a-z0-9]', '', str(s).lower())


def parse_range(text, year):
    """'June 22-25, 2027' / 'May 30 - June 3, 2027' / '8-12 March 2027' -> (start, end)."""
    s = str(text).replace('–', '-').replace('—', '-').replace(',', ' ')
    months = [(m.start(), MONTHS[m.group(1).lower()]) for m in re.finditer(
        r'(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?', s)]
    no_years = re.sub(r'\b(19|20)\d\d\b', '    ', s)
    days = [(m.start(), int(m.group(0))) for m in re.finditer(r'(?<!\d)\d{1,2}(?!\d)', no_years)]
    years = [int(y) for y in re.findall(r'\b(20\d\d)\b', s)]
    if not months or not days:
        return None
    day_first = s.strip()[:1].isdigit()

    def month_for(pos):
        before = [m for p, m in months if p < pos]
        after = [m for p, m in months if p > pos]
        if day_first:
            return after[0] if after else before[-1]
        return before[-1] if before else after[0]

    (p1, d1), (p2, d2) = days[0], days[-1]
    m1, m2 = month_for(p1), month_for(p2)
    y2 = years[-1] if years else int(year)
    y1 = y2 - 1 if m1 > m2 else y2
    try:
        return datetime.date(y1, m1, d1), datetime.date(y2, m2, d2)
    except ValueError:
        return None


def clean_place(p):
    p = re.sub(r'\s*\((hybrid|in[- ]person|virtual)[^)]*\)', '', str(p or ''), flags=re.I).strip()
    return '' if p.upper() in ('TBD', 'TBA', 'N/A') else p


def load_dataset(path):
    db = {}
    for f in glob.glob(os.path.join(path, 'conference', '*', '*.yml')):
        try:
            entries = yaml.safe_load(open(f, encoding='utf-8')) or []
        except yaml.YAMLError as e:
            print(f'  ! skipped {f}: {e}', file=sys.stderr)
            continue
        for c in entries:
            db[norm(c.get('title', ''))] = c
    return db


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: update_conferences.py <path to ccf-deadlines clone>')
    today = datetime.date.today()
    confs = json.load(open(LIST, encoding='utf-8'))
    overrides = json.load(open(OVERRIDES, encoding='utf-8'))
    db = load_dataset(sys.argv[1])
    print(f'→ {len(confs)} conferences on our list, {len(db)} in the dataset')

    items = []
    for c in confs:
        acr, tier = c['acronym'], c['tier']
        editions = []   # (start, end, place, link, year, note, source)

        for o in overrides.get(f'{acr}|{tier}', overrides.get(acr, [])):
            start = datetime.date.fromisoformat(o['start']) if o.get('start') else None
            end = datetime.date.fromisoformat(o['end']) if o.get('end') else start
            editions.append((start, end, o.get('place', ''), o.get('link', ''), o.get('year'), o.get('note', ''), 'manual'))

        ds = None if (acr, tier) in NO_DATASET else db.get(norm(ALIAS.get(acr, acr)))
        for e in (ds or {}).get('confs', []) or []:
            rng = parse_range(e.get('date', ''), e.get('year'))
            if rng:
                editions.append((rng[0], rng[1], clean_place(e.get('place')), e.get('link', ''), e.get('year'), '', 'ccfddl'))

        dated = [e for e in editions if e[0]]
        upcoming = sorted([e for e in dated if e[1] >= today], key=lambda e: (e[0], e[6] != 'manual'))
        past = sorted([e for e in dated if e[1] < today], key=lambda e: e[0])
        # an edition known only by year/place (no dates yet)
        undated = [e for e in editions if not e[0] and (e[4] or 0) >= today.year]

        item = dict(c)
        if upcoming:
            s, e, place, link, year, note, src = upcoming[0]
            item['next'] = {'start': s.isoformat(), 'end': e.isoformat(), 'place': place, 'link': link}
            if note:
                item['next']['note'] = note
        else:
            item['next'] = None
            if undated:
                _, _, place, link, year, note, _ = undated[0]
                item['announced'] = {k: v for k, v in (('year', year), ('place', place), ('link', link), ('note', note)) if v}
        if past:
            s, e, place, link, *_ = past[-1]
            item['last'] = {'start': s.isoformat(), 'end': e.isoformat(), 'place': place, 'link': link}
        items.append(item)

    known = sum(1 for i in items if i['next'])
    print(f'→ next edition known: {known}, to be announced: {len(items) - known}')
    payload = {'updated_at': today.isoformat(), 'count': len(items), 'items': items}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write('\n')
    print(f'✓ Wrote {OUT}')


if __name__ == '__main__':
    main()
