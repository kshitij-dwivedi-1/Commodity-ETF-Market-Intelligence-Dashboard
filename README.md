# Commodity & ETF Market Intelligence Dashboard

A Python ETL and analytics project for collecting commodity and ETF market data, normalizing it into a MySQL schema, detecting anomalies, generating forecast/correlation tables, and serving the data to a Power BI dashboard.

## Features

- Async market-data fetching with retries, per-provider rate limits, and structured logs.
- Config-driven API sources for commodities, ETFs, energy, metals, agricultural data, FX, and Yahoo Finance symbols.
- Pandas normalization into a canonical OHLCV schema: `symbol`, `ts`, `open`, `high`, `low`, `close`, `volume`, and `source`.
- Data-quality quarantine for failed fetches, invalid prices, missing timestamps, future timestamps, and duplicate symbol timestamps.
- Bulk upsert loader for MySQL with SQLite-compatible tests.
- Analytics modules for anomaly detection, rolling correlations, and short-horizon price forecasts.
- APScheduler runner with a Flask `/health` endpoint for scheduled refresh monitoring.
- Power BI model and visual design guide in `powerbi/dashboard_guide.md`.

## Project Structure

```text
analytics/                 Anomaly, correlation, and forecast modules
config/                    Runtime and API source configuration
db/                        MySQL schema and migrations
etl/                       Fetch, transform, load, and pipeline orchestration
powerbi/                   Power BI dashboard setup guide
scheduler/                 Scheduled ETL runner and health endpoint
scripts/                   Local utility scripts
tests/                     Unit tests for fetch, transform, and load behavior
output/                    Generated demo output artifacts
```

## Requirements

- Python 3.11+
- MySQL 8+ for production loading
- Power BI Desktop with the MySQL connector for dashboard visualization
- API keys for providers configured in `config/api_sources.yaml`

Install Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Configuration

Copy the example environment file and fill in your local credentials:

```powershell
Copy-Item .env.example .env
```

Common variables:

```text
DB_HOST=localhost
DB_PORT=3306
DB_NAME=market_intelligence
DB_USER=etl_user
DB_PASSWORD=changeme
ALPHA_VANTAGE_KEY=...
EIA_API_KEY=...
TWELVE_DATA_KEY=...
USDA_NASS_KEY=...
METALS_API_KEY=...
OPEN_EXCHANGE_RATES_KEY=...
```

Create the database schema:

```powershell
mysql -u root -p < db\schema.sql
```

## Run The ETL

Run one ETL cycle:

```powershell
python -c "from commodity_etf_dashboard.etl.pipeline import run; print(run())"
```

Run the scheduler with the Flask health endpoint:

```powershell
python scheduler\cron_runner.py
```

Then check:

```text
http://localhost:8080/health
```

## Tests

Run the unit test suite:

```powershell
python -m pytest
```

The tests cover fetch retry behavior, response normalization, validation/quarantine logic, SQLite-backed upsert behavior, and batch chunking.

## Demo Output

Generate deterministic demo artifacts without API keys or MySQL:

```powershell
python scripts\generate_demo_assets.py
```

Generated files:

- `output/sample_market_data.csv` - normalized OHLCV sample rows with anomaly flags.
- `output/etl_run_summary.json` - sample run summary and artifact list.
- `output/dashboard_snapshot.png` - static dashboard-style snapshot.
- `output/demo_video.mp4` - short MP4 walkthrough of the ETL flow and output metrics.

The demo data is fixed sample data for presentation and verification. Production data comes from the providers listed in `config/api_sources.yaml`.

## Power BI Dashboard

Follow `powerbi/dashboard_guide.md` to connect Power BI Desktop to MySQL using DirectQuery. Recommended visuals include:

- Live price ticker table
- Multi-symbol time-series line chart
- Predictive trend chart with confidence bounds
- Correlation heatmap
- Anomaly scatter plot
- Volume comparison bar chart
- ETF vs commodity KPI cards
- Anomaly event log

## Database Tables

- `symbols`
- `price_history`
- `correlation_matrix`
- `anomaly_events`
- `price_forecasts`
- `etl_runs`

## Troubleshooting

- If live ETL returns partial results, check provider API keys and rate limits first.
- If Power BI cannot connect, verify the MySQL ODBC connector bitness matches Power BI Desktop.
- If imports fail after renaming the checkout folder, keep the `commodity_etf_dashboard` shim package in place. It exposes the repository-root source folders under the stable import path used by tests and scripts.
