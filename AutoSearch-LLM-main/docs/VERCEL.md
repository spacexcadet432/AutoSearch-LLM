# Deploying the frontend to Vercel

The UI is TanStack Start + Vite with `nitro({ preset: "vercel" })` already
configured in `frontend/vite.config.ts`. No framework change is needed.

## 1. Push to GitHub

```bash
git add -A && git commit -m "Production-ready backend + frontend integration"
git push origin main
```

Confirm `.env` is **not** in the commit (it is gitignored).

## 2. Import the project into Vercel

Vercel → **Add New → Project** → import the repository.

## 3. Build settings

| Setting | Value |
|---|---|
| **Root Directory** | `frontend` ← must be set; not the repo root, not `New Frontend` |
| Framework Preset | Other (Vite/Nitro output is auto-detected) |
| Install Command | `npm install` |
| Build Command | `npm run build` |

`frontend/vercel.json` already pins the install/build commands.

> The repo contains a duplicate `New Frontend/` (the original Lovable export).
> **`frontend/` is the canonical app** wired to this backend.

## 4. Environment variables

Project → Settings → Environment Variables (scope: Production, and Preview if used):

| Name | Value |
|---|---|
| `VITE_PUBLIC_BACKEND_URL` | `https://api.your-domain.com` (your EC2 backend, **no trailing slash**) |

This is the only frontend variable. **No API keys belong in the frontend** — they
are either entered by the user at runtime or held server-side on EC2.

> `VITE_*` variables are inlined into the browser bundle at build time. Never put
> a secret in one. Changing it requires a redeploy.

## 5. Deploy

Click **Deploy**. Note the resulting origin, e.g. `https://autosearch-llm.vercel.app`.

## 6. Point CORS at the deployed origin

On EC2, add the exact Vercel origin to `/etc/autosearch/autosearch.env`:

```bash
AUTOSEARCH_ALLOWED_ORIGINS=https://autosearch-llm.vercel.app,http://localhost:3000
sudo systemctl restart autosearch
```

Origins must match scheme + host exactly and carry no trailing slash. Vercel
preview deployments get unique URLs, so add those too or test previews against a
permissive non-production backend.

## 7. Verify

```bash
# CORS from the deployed origin
curl -s -D- -o /dev/null https://api.your-domain.com/health \
  -H "Origin: https://autosearch-llm.vercel.app" | grep -i access-control-allow-origin
```

Then in the browser:

1. Load the Vercel URL — the page renders.
2. DevTools → Network: a `GET /health` fires on load. If the backend has its own
   credentials it returns `credentials_configured {llm:true, search:true}` and the
   API-key fields become optional.
3. Submit a query → `POST /query` returns 200 with `answer`, `sources`,
   `routing_decision`, `retrieval_status`, `grounded`.
4. Answer, routing panel, sources and latency badges render.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Cannot reach the backend at …" | CORS or backend down | Add the Vercel origin to `AUTOSEARCH_ALLOWED_ORIGINS`, restart, check `systemctl status` |
| "Missing VITE_PUBLIC_BACKEND_URL" | Variable unset or not rebuilt | Set it, then **redeploy** (build-time inlined) |
| Mixed-content blocked | `https` page calling `http` backend | Put TLS in front of EC2; the backend URL must be `https` |
| 404 / blank page | Wrong Root Directory | Set Root Directory to `frontend` |
| CORS preflight fails | Trailing slash / scheme mismatch | Origin must match exactly, no trailing slash |
