# GAF CMO Command Center - Design Spec

## Overview
A password-protected static dashboard hosted on GitHub Pages, with data refreshed every 30 minutes via GitHub Actions. Accessible from any device.

## Architecture
- **Frontend:** Single HTML page with vanilla JS, reads `data/dashboard.json`
- **Data pipeline:** Python script (`scripts/fetch_data.py`) run by GitHub Actions on cron
- **Hosting:** GitHub Pages (public repo, client-side password gate)
- **Secrets:** All API keys stored as GitHub Secrets, injected at Action runtime

## Data Sources & Panels

### 1. Brand Performance (Shopify)
- GAF + Revel revenue (today, 7d, 30d, 90d)
- Order count and AOV
- GP margin trend (from product data sheet)
- Channel split: online vs domestic vs commercial (where derivable)

### 2. Marketing Performance (GA4)
- Sessions, users, conversion rate (7d, 30d)
- Channel breakdown (organic, paid, direct, referral, social)
- Top landing pages by revenue

### 3. Campaign Health (HubSpot + Asana)
- Active marketing emails and their performance (open rate, click rate)
- Active campaigns from Asana campaign board with status/due dates

### 4. Customer Intelligence (Google Sheets - Profit Per X)
- CAC by customer segment (B2C Home Gym, B2C Online, B2B, etc.)
- ROAS by platform (Google Ads, Meta, Pinterest, etc.)
- Archetype breakdown

### 5. Team Execution (Asana)
- Tasks due this week across key projects
- Overdue task count
- Gary's board status

### 6. Weekly Scorecard
- Margin % (target: 40%+)
- Discount rate (target: <8%)
- Shipping recovery (target: 85%)
- Marketing spend ratio (target: 12%)
- Commercial channel share (target: growing)

## Security
- Client-side password gate using SHA-256 hash comparison
- Password stored hashed in the HTML - no plaintext
- Not enterprise-grade security, but sufficient for aggregate business metrics
- No PII or customer data exposed in dashboard.json

## File Structure
```
gaf-command-center/
  index.html              # Dashboard UI + password gate
  css/style.css           # Dashboard styles
  js/app.js               # Dashboard logic, chart rendering
  data/dashboard.json     # Auto-generated data (committed by Action)
  scripts/
    fetch_data.py         # Data aggregation script
    requirements.txt      # Python dependencies
  .github/workflows/
    refresh-data.yml      # Cron Action (every 30 min)
  docs/
    design.md             # This file
```

## Refresh Cadence
- GitHub Action runs every 30 minutes
- Each run: pull all APIs -> write dashboard.json -> commit + push
- Stale data indicator on dashboard shows last refresh time
