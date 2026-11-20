#!/usr/bin/env node
/**
 * fetch-ntis.mjs
 *
 * Pull the lab's ongoing national R&D projects from the NTIS OpenAPI
 * (국가R&D 과제검색) and write them to data/projects.json, which the
 * homepage reads.
 *
 * NTIS only answers calls from the IP registered with the API key, so this
 * cannot run on GitHub's servers. Two ways to use it:
 *
 *   1. On the registered PC:
 *        NTIS_API_KEY=xxx node scripts/fetch-ntis.mjs
 *   2. From saved API responses (XML files saved from the browser):
 *        NTIS_FILES=a.xml,b.xml node scripts/fetch-ntis.mjs
 *
 * Never commit the API key.
 *
 * Requirements: Node 18+ (built-in fetch). No external npm deps needed.
 */

import { writeFile, mkdir, readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_PATH  = resolve(__dirname, '..', 'data', 'projects.json');

const API_KEY  = process.env.NTIS_API_KEY;
const ENDPOINT = process.env.NTIS_ENDPOINT || 'https://www.ntis.go.kr/rndopen/openApi/public_project';
const DEBUG    = process.env.NTIS_DEBUG === '1';
const PAGE_SIZE = 100;
const MAX_PAGES = 5;

// Principal investigators to collect, with the English name shown on the site.
const PIS = [
  { ko: '전태준', en: 'Tae Joon Jun' },
  { ko: '김영학', en: 'Young-Hak Kim' },
];
// Same-name researchers elsewhere are excluded: the research agency must match.
const AGENCY_RX = /아산|울산대/;

const FILES = (process.env.NTIS_FILES || '').split(',').map(f => f.trim()).filter(Boolean);

if (!API_KEY && !FILES.length) {
  console.error('❌  Set NTIS_API_KEY (live call) or NTIS_FILES (saved responses)');
  process.exit(1);
}

// ---------- tiny XML helpers (the response is flat enough for this) ----------
// NTIS wraps the matched search word in an escaped <span>, so tags are
// stripped again after entities are decoded.
const decode = s => s
  .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1')
  .replace(/<[^>]+>/g, ' ')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&')
  .replace(/<\/?span[^>]*>/g, '')
  .replace(/\s+/g, ' ').trim();
const inner = (xml, tag) => {
  const m = xml.match(new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)</${tag}>`, 'i'));
  return m ? m[1] : '';
};
// text('ProjectTitle', 'Korean') -> text of <ProjectTitle><Korean>…</Korean></ProjectTitle>
const text = (xml, ...path) => {
  let cur = xml;
  for (const tag of path) { cur = inner(cur, tag); if (!cur) return ''; }
  return decode(cur);
};
const first = (...vals) => vals.find(v => v && v.length) || '';

// ---------- NTIS call ----------
async function fetchPage(name, start) {
  const url = new URL(ENDPOINT);
  url.searchParams.set('apprvKey', API_KEY);
  url.searchParams.set('collection', 'project');
  url.searchParams.set('SRWR', name);
  url.searchParams.set('searchFd', 'AU');          // AU = 연구책임자
  url.searchParams.set('searchRnkn', 'DATE/DESC');
  url.searchParams.set('startPosition', String(start));
  url.searchParams.set('displayCnt', String(PAGE_SIZE));
  const r = await fetch(url, { headers: { Accept: 'application/xml' } });
  const body = await r.text();
  if (!r.ok) throw new Error(`HTTP ${r.status} — ${body.slice(0, 300)}`);
  return body;
}

function parseHits(xml) {
  const hits = xml.match(/<HIT(?:\s[^>]*)?>[\s\S]*?<\/HIT>/gi) || [];
  return hits.map(h => {
    const period = inner(h, 'ProjectPeriod');
    return {
      number:    text(h, 'ProjectNumber'),
      title_ko:  first(text(h, 'ProjectTitle', 'Korean'), text(h, 'ProjectTitle')),
      title_en:  text(h, 'ProjectTitle', 'English'),
      pi_ko:     first(text(h, 'Manager', 'Name'), text(h, 'Manager')),
      agency:    first(text(h, 'ResearchAgency', 'Name'), text(h, 'ResearchAgency')),
      ministry:  first(text(h, 'Ministry', 'Name'), text(h, 'Ministry')),
      program:   text(h, 'BusinessName'),
      year:      parseInt(text(h, 'ProjectYear'), 10) || null,
      start:     first(text(period, 'TotalStart'), text(period, 'Start')),
      end:       first(text(period, 'TotalEnd'), text(period, 'End')),
      funds:     parseInt(text(h, 'TotalFunds').replace(/[^\d]/g, ''), 10) || null,
    };
  });
}

const toDate = s => {
  const d = (s || '').replace(/[^\d]/g, '');
  return d.length >= 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : '';
};

async function collect() {
  const all = [];
  if (FILES.length) {
    for (const f of FILES) {
      const hits = parseHits(await readFile(f, 'utf8'));
      console.log(`→ ${f}: ${hits.length} records`);
      all.push(...hits);
    }
    return all;
  }
  for (const pi of PIS) {
    console.log(`→ NTIS: records mentioning ${pi.en}`);
    for (let page = 0; page < MAX_PAGES; page++) {
      const xml = await fetchPage(pi.ko, page * PAGE_SIZE + 1);
      if (DEBUG && page === 0) {
        console.log('--- raw response (first 3000 chars) ---');
        console.log(xml.slice(0, 3000));
        console.log('--- end raw ---');
      }
      const hits = parseHits(xml);
      console.log(`  page ${page + 1}: ${hits.length} records`);
      if (!hits.length && page === 0) console.log(`  (no <HIT> found; response starts: ${xml.slice(0, 200).replace(/\s+/g, ' ')})`);
      all.push(...hits);
      if (hits.length < PAGE_SIZE) break;
    }
  }
  return all;
}

async function main() {
  const today = new Date().toISOString().slice(0, 10);
  const collected = await collect();
  console.log(`→ Total raw records: ${collected.length}`);

  // NTIS has one record per project-year, and the PI can change between years.
  // Merge the years of each project; the most recent year decides PI and agency.
  const norm = t => t.replace(/^\(주관\)/, '').replace(/\s/g, '');
  const byTitle = new Map();
  const seen = new Set();
  for (const h of collected) {
    if (!h.title_ko || seen.has(h.number)) continue;
    seen.add(h.number);
    const key = norm(h.title_ko);
    const start = toDate(h.start), end = toDate(h.end);
    const cur = byTitle.get(key);
    if (!cur) { byTitle.set(key, { ...h, start, end }); continue; }
    if (start && (!cur.start || start < cur.start)) cur.start = start;
    if (end && (!cur.end || end > cur.end)) cur.end = end;
    if ((h.year || 0) > (cur.year || 0)) {
      Object.assign(cur, { year: h.year, number: h.number, pi_ko: h.pi_ko, agency: h.agency, ministry: h.ministry, program: h.program, title_ko: h.title_ko, title_en: h.title_en || cur.title_en });
    } else if (!cur.title_en && h.title_en) cur.title_en = h.title_en;
  }
  console.log(`→ Distinct projects: ${byTitle.size}`);

  // keep projects currently led by one of our PIs at our institutions
  const thisYear = Number(today.slice(0, 4));
  const items = [...byTitle.values()]
    .map(p => ({ ...p, pi: (PIS.find(x => x.ko === p.pi_ko.replace(/\s/g, '')) || {}).en }))
    .filter(p => p.pi && AGENCY_RX.test(p.agency))
    .filter(p => p.end ? p.end >= today : (p.year || 0) >= thisYear)   // ongoing
    .map(({ funds, ...p }) => p)
    .sort((a, b) => (b.start || '').localeCompare(a.start || '') || a.title_ko.localeCompare(b.title_ko));
  console.log(`→ Ongoing projects led by lab PIs: ${items.length}`);
  for (const p of items) console.log(`  · ${p.start}–${p.end} ${p.pi} (${p.year}) | ${p.title_ko}`);

  await mkdir(dirname(OUT_PATH), { recursive: true });
  const payload = { updated_at: today, source: 'ntis', count: items.length, items };
  await writeFile(OUT_PATH, JSON.stringify(payload, null, 2) + '\n', 'utf8');
  console.log(`✓ Wrote ${OUT_PATH}`);
}

main().catch(err => {
  console.error('✗ Failed:', API_KEY ? String(err).split(API_KEY).join('***') : String(err));
  process.exit(1);
});
