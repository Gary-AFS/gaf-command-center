# GAF Command Center

CMO dashboard for AFS Group / GAF. Password-protected. Data refreshed every 30 minutes via GitHub Actions.

## Setup

1. Add GitHub Secrets (Settings > Secrets > Actions):
   - `SHOPIFY_GAF_CLIENT_ID`
   - `SHOPIFY_GAF_CLIENT_SECRET`
   - `SHOPIFY_REVEL_CLIENT_ID`
   - `SHOPIFY_REVEL_CLIENT_SECRET`
   - `HUBSPOT_PAT`
   - `GA4_CREDENTIALS_JSON` (base64-encoded service account JSON)
   - `ASANA_PAT`

2. Enable GitHub Pages (Settings > Pages > Source: Deploy from branch, Branch: main, Folder: / (root))

3. Run the workflow manually or wait for the next 30-minute cron cycle.
