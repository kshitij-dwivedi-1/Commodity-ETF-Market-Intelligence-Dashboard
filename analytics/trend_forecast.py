"""Linear-regression trend forecasting with moving average context."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


def forecast_prices(symbol_id: int, horizon_days: int = 7, connection: Any | None = None) -> pd.DataFrame:
    """Forecast future closes from the last 90 days and upsert forecast outputs."""
    if connection is None:
        raise ValueError("connection is required")
    frame = pd.read_sql(
        "SELECT ts, close FROM price_history WHERE symbol_id = %s AND ts >= UTC_TIMESTAMP() - INTERVAL 90 DAY ORDER BY ts",
        connection,
        params=(symbol_id,),
    )
    if len(frame) < 2:
        return pd.DataFrame(columns=["forecast_ts", "predicted", "lower_bound", "upper_bound", "sma_7", "sma_14", "sma_30"])

    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    frame["day_index"] = np.arange(len(frame))
    x = frame[["day_index"]].to_numpy()
    y = frame["close"].astype(float).to_numpy()
    model = LinearRegression().fit(x, y)
    residual_std = float(np.std(y - model.predict(x), ddof=1)) if len(frame) > 2 else 0.0
    last_ts = frame["ts"].max()
    future_indexes = np.arange(len(frame), len(frame) + horizon_days).reshape(-1, 1)
    predictions = model.predict(future_indexes)
    margin = residual_std * 1.96
    latest_sma_7 = float(frame["close"].rolling(7, min_periods=1).mean().iloc[-1])
    latest_sma_14 = float(frame["close"].rolling(14, min_periods=1).mean().iloc[-1])
    latest_sma_30 = float(frame["close"].rolling(30, min_periods=1).mean().iloc[-1])
    forecast = pd.DataFrame(
        {
            "forecast_ts": [last_ts + timedelta(days=offset) for offset in range(1, horizon_days + 1)],
            "predicted": predictions,
            "lower_bound": predictions - margin,
            "upper_bound": predictions + margin,
            "sma_7": latest_sma_7,
            "sma_14": latest_sma_14,
            "sma_30": latest_sma_30,
        }
    )
    cursor = connection.cursor()
    cursor.executemany(
        "INSERT INTO price_forecasts (symbol_id, forecast_ts, predicted, lower_bound, upper_bound, model) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE predicted = VALUES(predicted), lower_bound = VALUES(lower_bound), "
        "upper_bound = VALUES(upper_bound), model = VALUES(model), created_at = CURRENT_TIMESTAMP",
        [
            (
                symbol_id,
                row.forecast_ts.to_pydatetime().replace(tzinfo=None),
                float(row.predicted),
                float(row.lower_bound),
                float(row.upper_bound),
                "linear_regression_sma",
            )
            for row in forecast.itertuples(index=False)
        ],
    )
    connection.commit()
    return forecast
