# Static clone (GitHub Pages)

A sign-in-free copy of the Waypoint web app that anyone can click through. It is
the real web app (`apps/waypoint/web`) built as a static site, with a scrubbed
snapshot of the live data. There's no backend: no sign-in, no Foundry, no API.

- **URL:** <https://caldova.github.io/waypoint/>
- **Branch:** `snapshot/clone` (long-lived, never merged to `main`)
- **Deploys:** every push to `snapshot/clone` runs
  [`static-clone-pages.yml`](../.github/workflows/static-clone-pages.yml)

## How it works

`WAYPOINT_STATIC=true` (set by `npm run build:static`) switches the build:

| Piece | Static behavior |
| --- | --- |
| Rendering | Every page is prerendered in English and Spanish; `404.html` covers other paths |
| Sign-in | Starts signed in as "Caldova Analyst". Sign out / Sign in just toggle locally |
| Data | `lib/staticApi.ts` answers `/api/*` from `static-data/snapshot.json` |
| Dates | Shifted forward by whole days so the newest run is always recent |
| Run assurance | Single and batch runs are simulated: the run shows up in Activity, experts report one by one, and after ~30s it completes with that invoice's latest real result |
| Telemetry | Off |
| Quality page | Adds the two-part contract-policy expert story from the canvases: Part 1, Foundry Agent Optimizer (new assets, same model; from Optimizer Diff), and Part 2, RFT (same assets, fine-tuned MAI model; from RFT Cost Quality, with the cost slider). The rest of the page shows the matching MAI RFT eval results |

The normal SSR build is unchanged when the flag is unset.

## Refresh the data

The snapshot comes from the live API as a signed-in user.

1. Sign in to the Waypoint web app, open DevTools → Network, click any `/api/`
   request, and copy the `Authorization` header value (without `Bearer`).
2. Capture:

   ```bash
   cd apps/waypoint/web
   export WAYPOINT_API_URL="https://$(gh variable get WAYPOINT_API_CUSTOM_DOMAIN --env caldova --repo caldova/waypoint)"
   export WAYPOINT_API_TOKEN="<paste>"
   npm run snapshot:static
   ```

3. Read the report it prints. Emails outside synthetic domains are swapped for
   sample identities automatically. Add any real names it lists to
   `scripts/static-scrub.local.json` (same shape as
   `scripts/static-scrub.example.json`) and run it again. That file is
   gitignored because it names the people being hidden; keep it locally or point
   `WAYPOINT_SCRUB_FILE` at a copy outside the repo. **The repo is public**, so
   check `git diff` before pushing.
4. Commit `static-data/` and push to `snapshot/clone`.

`WAYPOINT_API_KEY` (reader `x-api-key`) also works if the API has key auth enabled.

## Preview locally

```bash
cd apps/waypoint/web
npm run build:static
mkdir -p /tmp/wp && ln -sfn "$PWD/build/client" /tmp/wp/waypoint
python3 -m http.server 4173 --directory /tmp/wp
# open http://127.0.0.1:4173/waypoint/
```

## Keep up with main

```bash
git switch snapshot/clone
git merge origin/main
npm --prefix apps/waypoint/web run build:static   # make sure it still builds
git push
```

Static-only code is behind `WAYPOINT_STATIC` / `STATIC_MODE`, so merges usually
touch only a few lines. If a new page calls a new `/api/*` endpoint, add it to
`scripts/snapshot-static-data.mjs` and recapture.

## One-time setup

Needs a repo admin:

```bash
# Publish Pages from GitHub Actions
gh api -X POST repos/caldova/waypoint/pages -f build_type=workflow
# Let snapshot/clone deploy to the github-pages environment
gh api -X POST repos/caldova/waypoint/environments/github-pages/deployment-branch-policies \
  -f name=snapshot/clone -f type=branch
```
