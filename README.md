## Amber Balance (Home Assistant)

Amber Balance pulls your Amber usage/export data and calculates your live billing position. It supports custom billing cycle start days, separates fees from energy costs, and exposes rich diagnostics/metrics for dashboards.

### Features
- Automatic site discovery (or specify a site ID manually).
- Configurable billing start day (1–28) for off-cycle billing dates.
- Fee inputs as number entities (daily surcharge in cents, monthly subscription in AUD).
- Manual refresh button plus hourly polling.
- Metric sensors for totals (import/export/net kWh, energy value, fees, projected total) and statistics (best/worst/most-average day, days in credit/owing).
- Diagnostic sensors for Amber site metadata and a last-update timestamp.

### Installation (HACS)
1) Add this repo to HACS: `HACS → Integrations → Custom repositories → https://github.com/mplinuxgeek/ha_amber_balance.git` (category: Integration).
2) Install **Amber Balance** and restart Home Assistant.
3) Go to **Settings → Devices & services → Add integration → Amber Balance** and follow the prompts.

### Manual installation
1) Copy `custom_components/amber_balance` into your Home Assistant `config/custom_components` directory.
2) Restart Home Assistant.
3) Add **Amber Balance** from **Settings → Devices & services**.

### Configuration options
- `token` (required): Amber API token.
- `site_id` (optional): pick a site; if omitted, all sites are discovered and added.
- `name` (optional): display name; defaults to `Amber Balance`.
- `billing_start_day` (optional): day of month your billing cycle starts (1–28); defaults to 1.
- `surcharge_cents` (optional): daily surcharge in cents; defaults to 104.5.
- `subscription` (optional): monthly subscription fee in AUD; defaults to 19.0.

After setup you can adjust surcharge/subscription in the two number entities; updates persist to options and recalc immediately.

### Entities created (per site)
- Sensor: `..._position` (overall month/cycle position) with attributes including `recent_daily` for dashboards.
- Metric sensors: import/export/net kWh, import/export $, before-fees, surcharge, subscription, fees, projected month total, average daily cost, days elapsed/remaining, days in credit/owing, best/worst/most-average day values (with dates).
- Diagnostic sensors: NMI, network, status, active from, channels.
- Button: manual refresh.
- Numbers: daily surcharge (cents), monthly subscription (AUD).
- Sensor: last update timestamp.
