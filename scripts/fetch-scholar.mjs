#!/usr/bin/env node
/**
 * fetch-scholar.mjs
 *
 * Pull a Google Scholar author's publication list through SerpAPI
 * and write it out as data/publications.json, which the homepage reads.
 *
 * Usage (local):
 *   SERPAPI_KEY=xxx SCHOLAR_USER_ID=-a2slUgAAAAJ node scripts/fetch-scholar.mjs
 *
 * Runs automatically via .github/workflows/update-publications.yml
 *
 * Requirements: Node 18+ (built-in fetch). No external npm deps needed.
 */

import { writeFile, mkdir, readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_PATH  = resolve(__dirname, '..', 'data', 'publications.json');

const API_KEY = process.env.SERPAPI_KEY;
const USER_ID = process.env.SCHOLAR_USER_ID || '-a2slUgAAAAJ';
const MAX_PAGES = parseInt(process.env.MAX_PAGES || '4', 10); // 100 × 4 = 400 papers max
const PAGE_SIZE = 100;

if (!API_KEY) {
  console.error('❌  Missing SERPAPI_KEY env var');
  process.exit(1);
}

// ---------- topic tagging heuristic ----------
const TAG_RULES = [
  [/\b(LLM|language model|GPT|BERT|prompt|RAG|NLP)\b/i, 'AI'],
  [/\b(deep learning|neural|CNN|transformer|machine learning|multimodal)\b/i, 'AI'],
  [/\b(privacy|de-identif|de-id|GAN|differential privacy|security|safety|injection)\b/i, 'Security'],
  [/\b(cohort|epidemiolog|survivor|lipoprotein|SCORE|mortality|hypertension|stroke|diabetes)\b/i, 'Clinical'],
  [/\b(EMR|EHR|electronic medical|clinical|hospital|discharge|warfarin|ICD)\b/i, 'Clinical'],
];
const classify = (title = '', venue = '') => {
  const text = `${title} ${venue}`;
  for (const [rx, tag] of TAG_RULES) if (rx.test(text)) return tag;
  return 'Other';
};

// ---------- SerpAPI calls ----------
async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} — ${await r.text()}`);
  return r.json();
}

async function fetchAuthorPage(start) {
  const url = new URL('https://serpapi.com/search.json');
  url.searchParams.set('engine', 'google_scholar_author');
  url.searchParams.set('author_id', USER_ID);
  url.searchParams.set('hl', 'en');
  url.searchParams.set('num', String(PAGE_SIZE));
  url.searchParams.set('start', String(start));
  url.searchParams.set('sort', 'pubdate');
  url.searchParams.set('api_key', API_KEY);
  return fetchJson(url.toString());
}

async function main() {
  console.log(`→ Fetching Google Scholar profile: ${USER_ID}`);
  const all = [];
  for (let page = 0; page < MAX_PAGES; page++) {
    const start = page * PAGE_SIZE;
    const data = await fetchAuthorPage(start);
    const batch = data.articles || [];
    console.log(`  page ${page + 1}: +${batch.length} papers`);
    all.push(...batch);
    if (batch.length < PAGE_SIZE) break; // last page
  }
  console.log(`→ Total raw: ${all.length}`);

  // ---------- normalize ----------
  const items = all
    .map(a => {
      const year = parseInt(a.year, 10);
      const title = (a.title || '').trim();
      const authors = (a.authors || '').trim();
      const venue = (a.publication || '').trim();
      const link = a.link || '';
      if (!title || !year || Number.isNaN(year)) return null;
      return {
        year,
        title,
        authors,
        venue,
        tag: classify(title, venue),
        link,
        citation_id: a.citation_id || '',
        cited_by: a.cited_by?.value || 0,
      };
    })
    .filter(Boolean)
    // newest first, then by cites within the year
    .sort((a, b) => (b.year - a.year) || (b.cited_by - a.cited_by));

  console.log(`→ Kept: ${items.length}`);

  // ---------- preserve manual overrides ----------
  // If data/publications.json has items with the same citation_id or title,
  // copy over fields that are missing from Scholar (e.g. custom tag) — but
  // don't block new entries.
  let overrides = {};
  try {
    const existing = JSON.parse(await readFile(OUT_PATH, 'utf8'));
    if (existing && Array.isArray(existing.items)) {
      for (const it of existing.items) {
        if (it.override === true) {
          const key = it.citation_id || it.title?.toLowerCase();
          if (key) overrides[key] = it;
        }
      }
    }
  } catch { /* first run */ }

  const finalItems = items.map(it => {
    const key = it.citation_id || it.title.toLowerCase();
    return overrides[key] ? { ...it, ...overrides[key] } : it;
  });

  // ---------- write ----------
  await mkdir(dirname(OUT_PATH), { recursive: true });
  const payload = {
    updated_at: new Date().toISOString().slice(0, 10),
    source: 'google_scholar',
    scholar_user_id: USER_ID,
    count: finalItems.length,
    items: finalItems,
  };
  await writeFile(OUT_PATH, JSON.stringify(payload, null, 2) + '\n', 'utf8');
  console.log(`✓ Wrote ${OUT_PATH}`);
}

main().catch(err => {
  console.error('✗ Failed:', err);
  process.exit(1);
});
