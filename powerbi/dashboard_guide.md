# Power BI Dashboard Guide

## Connection

1. Install the MySQL ODBC connector that matches your Power BI Desktop bitness.
2. Open Power BI Desktop and select **Get Data -> MySQL database**.
3. Enter the MySQL host and database from `.env`.
4. Choose **DirectQuery** so visuals read the latest 15-minute refresh cycle.
5. Import `symbols`, `price_history`, `correlation_matrix`, `anomaly_events`, `price_forecasts`, and `etl_runs`.

## Model Relationships

- `symbols.id` -> `price_history.symbol_id`
- `symbols.id` -> `anomaly_events.symbol_id`
- `symbols.id` -> `price_forecasts.symbol_id`
- `symbols.id` -> `correlation_matrix.symbol_a_id`
- Duplicate `symbols` as `symbols_b` for `correlation_matrix.symbol_b_id`

## Visualization 1: Live Price Ticker Table

Source: `price_history` joined to `symbols`.
Columns: Symbol, Name, Latest Close, Change%, Volume, Last Updated.
Filter to the latest timestamp per symbol and set page refresh to 15 minutes.

## Visualization 2: Multi-Symbol Time Series Line Chart

Source: last 30 days from `price_history`.
X-axis: `ts`.
Y-axis: close normalized to percent change from period start.
Slicer: symbol multiselect.
Tooltip: open, high, low, close, volume, source.

## Visualization 3: Predictive Trend Analysis

Sources: `price_history` and `price_forecasts`.
Show historical close for 90 days as a solid line.
Show forecasted `predicted` for 7 days forward as a dashed line.
Use `lower_bound` and `upper_bound` as the confidence band.
Add a symbol slicer.

## Visualization 4: Correlation Heatmap

Source: `correlation_matrix`.
Rows: symbol A name.
Columns: symbol B name.
Values: `correlation`.
Filter: `window_days = 30`.
Conditional formatting: red at -1, white at 0, green at +1.

## Visualization 5: Anomaly Detection Scatter Plot

Source: `price_history` filtered where `is_anomaly = 1`.
X-axis: `ts`.
Y-axis: `close`.
Color: z-score magnitude from `anomaly_events`.
Tooltip: symbol, z-score, method.
Add a grey background line for full price history.

## Visualization 6: Volume Bar Chart

Source: `price_history` joined to `symbols`.
Display top 10 symbols by average daily volume.
Compare last 7 days against previous 7 days.
Color: ETF blue, commodity orange.

## Visualization 7: ETF vs Commodity Performance KPI Cards

Create 8 KPI cards covering ETF and commodity averages for 1D%, 1W%, and 1M%.
Use green for positive movement and red for negative movement.
Add a 7-day sparkline to each card.

## Visualization 8: Anomaly Event Log Table

Source: `anomaly_events` joined to `symbols`.
Columns: Timestamp, Symbol, Price, Z-Score, Method, Flagged At.
Sort most recent first.
Conditional row highlight: `z_score > 4` uses a red background.
