# Clanstack hub (H1)
The always-on node of the free ladder (D-089). Logic lives in `engine/crates/hub-core` (tested in CI);
this crate only connects it to Cloudflare Workers and a SQLite-backed Durable Object.

- Endpoints: `GET /health`, `GET /status`, `GET /pull?after=N&limit=M`, `POST /push`, `POST /import` (last two need `Bearer HUB_WRITE_TOKEN`).
- Local run: `npx wrangler@4 dev --local` with a `.dev.vars` file holding `HUB_WRITE_TOKEN` and `IMPORTER_SEED` (never committed).
- Deploy: automatic after green CI on main (`.github/workflows/hub-deploy.yml`), once the owner adds the Cloudflare secrets.
- Tested locally 2026-11-06: 24 Studio events imported as 25 signed facts (importer identity + 24), re-import added 0,
  write without token → 401, restart kept all 25 with the chain verified.
