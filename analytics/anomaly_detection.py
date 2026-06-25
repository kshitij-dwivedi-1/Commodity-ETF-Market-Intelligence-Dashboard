"""Rolling Z-score and IQR anomaly detection for close prices."""

from __future__ import annotations

import pandas as pd


def detect_anomalies(df: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """Flag rows where rolling Z-score and rolling IQR methods both agree."""
    if df.empty:
        result = df.copy()
        result["z_score"] = pd.Series(dtype="float64")
        result["iqr_flag"] = pd.Series(dtype="boolean")
        result["is_anomaly"] = pd.Series(dtype="int64")
        return result

    working = df.sort_values(["symbol", "ts"]).copy()
    grouped = working.groupby("symbol", group_keys=False)["close"]
    rolling_mean = grouped.transform(lambda series: series.rolling(window=window, min_periods=5).mean())
    rolling_std = grouped.transform(lambda series: series.rolling(window=window, min_periods=5).std())
    working["z_score"] = ((working["close"] - rolling_mean) / rolling_std.replace(0, pd.NA)).fillna(0.0)

    q1 = grouped.transform(lambda series: series.rolling(window=window, min_periods=5).quantile(0.25))
    q3 = grouped.transform(lambda series: series.rolling(window=window, min_periods=5).quantile(0.75))
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    working["iqr_flag"] = (working["close"] < lower) | (working["close"] > upper)
    working["is_anomaly"] = ((working["z_score"].abs() > 3.0) & working["iqr_flag"]).astype(int)
    working["method"] = working["is_anomaly"].map({1: "zscore_iqr", 0: None})
    return working
