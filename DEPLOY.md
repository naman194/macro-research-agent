# Deployment guide — Railway

This guide deploys the **same repo** (no fork, no rewrite) to Railway, which gives you:

- HTTPS URL accessible from anywhere
- Persistent volume for the SQLite caches (`data_cache/`)
- Secrets via env vars (your `.env` doesn't get committed)
- ~$5/month (effectively free with Railway's $5 monthly credit on Hobby plan)
- One-click redeploy on every `git push`

Estimated time: **15 minutes** end-to-end.

---

## What this deployment includes

- Password gate at the front (single shared password via `SHARED_PASSWORD` env var)
- All system libraries weasyprint needs (`nixpacks.toml` handles it)
- All Python dependencies (`requirements.txt`)
- Streamlit started with `--server.address=0.0.0.0` so Railway can route to it
- Health check at `/_stcore/health` so Railway knows when the app is live

## Before you start

You need:
- A GitHub account (you already have one — repo is at `naman194/macro-research-agent`)
- Your `.env` values handy (you'll paste these as Railway secrets):
  - `ANTHROPIC_API_KEY`
  - `FRED_API_KEY` (optional — US macro panel is empty without it)
  - `SCREENER_PREMIUM_SESSIONID` (optional — unlocks 10y historical financials)
  - any other keys your local `.env` has

---

## Step-by-step

### 1. Sign up at Railway

1. Open https://railway.app
2. Click **Login** → choose **Sign in with GitHub** (uses your existing account)
3. Authorize Railway to read your public repos (it doesn't see private ones unless you grant)

### 2. Create the project

1. Click **+ New Project**
2. Choose **Deploy from GitHub repo**
3. If your repo (`naman194/macro-research-agent`) doesn't appear, click **Configure GitHub App** and grant Railway access to that specific repo
4. Pick `naman194/macro-research-agent` from the list
5. Railway starts the first build immediately

The first build takes ~5-7 minutes (installs apt packages + Python deps). Watch progress in the **Deployments** tab.

### 3. Add env secrets

While the first build runs, click into the service → **Variables** tab → **Raw Editor**. Paste, replacing values with your actual keys:

```
ANTHROPIC_API_KEY=sk-ant-...
FRED_API_KEY=...
SCREENER_PREMIUM_SESSIONID=...
SHARED_PASSWORD=<pick-a-strong-password-here>
```

Save. Railway will redeploy automatically with the new env.

> **Important:** `SHARED_PASSWORD` is what gates access. Without it set, the app is public to anyone with the URL — don't ship without it.

### 4. Attach a persistent volume

Without this, your `data_cache/` (concall archive, performance tracker, etc.) gets wiped on every redeploy.

1. Same service → **Settings** tab → scroll to **Volumes**
2. Click **Add Volume**
3. Mount path: `/app/data_cache`
4. Size: 1 GB is plenty to start
5. Save

The volume persists across redeploys and restarts.

### 5. Get your URL

1. Service → **Settings** → **Networking**
2. Click **Generate Domain** → Railway gives you `something-production.up.railway.app`
3. Optional: under **Custom Domain**, attach your own (e.g. `research.yourdomain.com`)

### 6. Test

1. Open the URL
2. You should see the password screen
3. Enter the `SHARED_PASSWORD` value you set
4. Sidebar should show all groups (Start, Daily, Stock Ideas, Deep Analysis, etc.)
5. Click around — every view should work the same as `localhost:8501`

---

## Redeploys — every time you push code

Once connected, every `git push origin main` triggers an automatic Railway redeploy. The volume and env vars persist, so concall archive + secrets carry across.

To deploy a fresh build manually: **Deployments** tab → **... menu** → **Redeploy**.

---

## Troubleshooting

**Build fails on `weasyprint` install**
→ The `nixpacks.toml` should fix this. If it still fails, switch the build to a Dockerfile (open issue, we'll write one).

**App hangs at "Please wait…"**
→ Streamlit can be slow on first request after a long idle. Refresh after 30s. If it persistently hangs, check Railway logs for the actual error.

**`pypdf` / concall extraction broken**
→ Verify `pypdf` is in `requirements.txt` (it should be; added during deploy prep).

**Forensics / Reverse DCF return "no data"**
→ Your `SCREENER_PREMIUM_SESSIONID` cookie may have expired (they last ~30 days). Re-paste a fresh one in Railway Variables.

**Want to log out?**
→ The password gate keeps you signed in for that browser session. Close the browser tab to clear, or rotate `SHARED_PASSWORD` in Railway Variables to force everyone out.

---

## Cost-control notes

- Railway charges by usage. A Streamlit app idling at 256 MB RAM + minimal CPU runs at roughly **$2-4/month**.
- Anthropic calls (concall analysis, research notes, daily brief) are the bigger line item — budget on the order of **₹500-2000/month** depending on how many notes you generate. Set a `max_tokens` ceiling in `src/config.py` if you want to cap.
- Use Railway's **Usage** tab to monitor.

---

## Alternative platforms (if Railway doesn't fit)

- **Render.com** — very similar, similar pricing. Same `Procfile` works.
- **Fly.io** — needs a `fly.toml`; more control, slightly steeper learning curve.
- **DigitalOcean App Platform** — clean UI, ~$5/month minimum.
- **Cloudflare Tunnel + your Mac** — free, but your Mac has to stay on. Use only if cost is the main constraint.

All four read the same `requirements.txt` + `Procfile`. The deploy steps differ but the artifacts are the same.

---

## Security upgrade path

The single shared password is fine for desk use. If you ever want per-user audit:

- Replace the `SHARED_PASSWORD` block in `app.py` with **streamlit-authenticator** (yaml config, hashed passwords)
- Or put **Cloudflare Access** in front of the Railway domain — zero-trust gate with email-based auth, free up to 50 users, no code change in the app

Both are 30-minute upgrades whenever you want them.
