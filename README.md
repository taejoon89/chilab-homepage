# CHILab Homepage

Editorial, auto-updating homepage for the **Computational Health Informatics Laboratory**.

## Publications auto-update (SerpAPI + GitHub Actions)

The Publications section reads from `data/publications.json`.
That file is regenerated weekly from Google Scholar via SerpAPI.

### One-time setup

1. **Get a SerpAPI key** — free plan = 100 queries / month. Sign up at https://serpapi.com.
   One run of the sync costs 1–4 queries (depending on paper count), so weekly updates stay well under the free cap.

2. **Push this project to GitHub.** On the repo page:
   - *Settings → Secrets and variables → Actions → New repository secret*
   - Name: `SERPAPI_KEY`   Value: *(paste your key)*
   - *(optional)* Add a **variable** (not secret) named `SCHOLAR_USER_ID` to override the default author.
     The ID is the `user=` query in your Scholar URL. Current: `-a2slUgAAAAJ`.

3. **Trigger the first run** — *Actions → Update publications from Google Scholar → Run workflow*.
   The workflow is also scheduled every Monday 12:00 KST.

4. Commit of `data/publications.json` happens automatically if anything changed.

### Running locally

```bash
export SERPAPI_KEY=xxxxxxxx
export SCHOLAR_USER_ID=-a2slUgAAAAJ
node scripts/fetch-scholar.mjs
```

Node 18+ required (built-in `fetch`). No npm install step.

### Manual overrides

You can hand-edit any item in `data/publications.json`. To make the next
sync *preserve your edits* for that paper, add `"override": true` to the item —
the script will merge your fields on top of the fresh Scholar row.

### File layout

| Path | Purpose |
|---|---|
| `index.html` | The full homepage (React + inline JSX) |
| `data/publications.json` | The source of truth for the Publications section |
| `scripts/fetch-scholar.mjs` | SerpAPI → JSON sync script |
| `.github/workflows/update-publications.yml` | Weekly CI job |

### Fallback

If SerpAPI becomes unavailable or you don't want to use it, the JSON file
is a normal hand-editable file — just add/remove items by hand and the
homepage will reflect the change on the next page load.
