# Vibe-Trading Wiki

Static source for `https://vibetrading.wiki`.

## Local preview

```bash
cd wiki
python3 -m http.server 8088
```

Open `http://localhost:8088/home/` for the landing page and these wiki sections:

- `http://localhost:8088/docs/`
- `http://localhost:8088/tutorials/`
- `http://localhost:8088/alpha-library/`
- `http://localhost:8088/research-lab/`

Direct docs URLs such as `/docs/latest/getting-started/vibe-trading-overview` are handled by Cloudflare Pages via `_redirects`. The simple Python preview server does not apply those rewrite rules, so use `/docs/` as the local entry point.

## Known asset TODOs

- `assets/feature-cross-market-data-backtesting.png` — **stale bitmap, needs
  re-authoring.** It still depicts five cross-market source panels (Hong Kong,
  US, crypto, commodities, forex), but the US + Canada scope change removed every
  one of those panels except US (Canada is in scope but was never depicted). The
  surrounding copy in `home/index.html` already says "US and Canada equity market
  data", so the illustration and the text disagree. Replace it with a US + Canada
  illustration (or at least a US-only one) that matches the reduced scope. The
  same note lives next to the `<img>` in `home/index.html` as a `TODO(assets)`
  HTML comment; this entry is the durable copy so the replacement is tracked
  outside a single HTML comment.

## Cloudflare Pages

- Project root: `wiki`
- Build command: leave empty
- Output directory: `.`
- Custom domain: `vibetrading.wiki`

The site is static and needs no build step. The only dynamic piece is a small
analytics layer in `functions/` (Cloudflare Pages Functions): `_middleware.js`
classifies each page request as AI-agent / bot / human by User-Agent and counts
it into a D1 database (`vibetrading-analytics`, binding `DB`), and
`api/stats.js` serves the footer's aggregate counts alongside public PyPI and
GitHub numbers. The counter is anonymous and first-party — no cookies, no
per-visitor identifier, no IP retention.
