# 社内FAQ AI — Landing page

Single self-contained `index.html` (no build step, no dependencies). Deploys to Vercel, separate from the app itself (which runs on the VPS at `app.shanaiai.com`).

## Deploy (one-time setup)

1. Push this repo to GitHub (if not already): `git push`
2. At [vercel.com](https://vercel.com) → **Add New → Project** → import this GitHub repo
3. In the import settings, set **Root Directory** to `landing`
4. Framework preset: **Other** (it's a static file, no build command needed)
5. Deploy

## Point the domain at it

1. In the Vercel project → **Settings → Domains** → add `shanaiai.com` and `www.shanaiai.com`
2. Vercel will show the exact DNS records to set (usually an `A` record for the apex and a `CNAME` for `www`) — follow what it displays there, since Vercel's target values can change
3. Update those records at your registrar (same place you added the `app` A record earlier)
4. `app.shanaiai.com` is untouched — it keeps pointing at the VPS via the existing A record

After DNS propagates, `shanaiai.com` serves this landing page and `app.shanaiai.com` continues serving the product, both with automatic HTTPS.

## Updating

Edit `index.html`, commit, push — Vercel redeploys automatically on every push to the connected branch.
