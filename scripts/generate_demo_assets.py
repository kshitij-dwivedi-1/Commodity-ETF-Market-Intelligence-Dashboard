"""Generate deterministic sample output and a short demo video."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from commodity_etf_dashboard.analytics.anomaly_detection import detect_anomalies
from commodity_etf_dashboard.etl.transformer import transform_all

OUTPUT_DIR = PROJECT_ROOT / "output"


def build_sample_raw() -> list[dict[str, object]]:
    """Create fixed raw API-like responses for the demo artifacts."""
    dates = pd.date_range("2026-05-01", periods=30, freq="D", tz="UTC")
    spy_records = []
    qqq_records = []
    for index, day in enumerate(dates):
        spy_close = 522 + index * 0.65 + np.sin(index / 3) * 2.2
        qqq_close = 444 + index * 0.9 + np.cos(index / 4) * 2.8
        if index == 23:
            spy_close += 28
        spy_records.append(
            {
                "Date": day.isoformat(),
                "Open": round(spy_close - 1.1, 2),
                "High": round(spy_close + 2.0, 2),
                "Low": round(spy_close - 2.3, 2),
                "Close": round(spy_close, 2),
                "Volume": 70_000_000 + index * 425_000,
            }
        )
        qqq_records.append(
            {
                "Date": day.isoformat(),
                "Open": round(qqq_close - 1.4, 2),
                "High": round(qqq_close + 2.6, 2),
                "Low": round(qqq_close - 2.0, 2),
                "Close": round(qqq_close, 2),
                "Volume": 42_000_000 + index * 315_000,
            }
        )

    gold_series = {}
    for index, day in enumerate(dates):
        close = 2315 + index * 2.8 + np.sin(index / 5) * 8
        gold_series[day.strftime("%Y-%m-%d")] = {
            "1. open": f"{close - 5:.2f}",
            "2. high": f"{close + 12:.2f}",
            "3. low": f"{close - 11:.2f}",
            "4. close": f"{close:.2f}",
            "5. volume": str(1_200_000 + index * 22_000),
        }

    return [
        {
            "symbol": "SPY",
            "provider": "yahoo_finance",
            "data": {"records": spy_records},
        },
        {
            "symbol": "QQQ",
            "provider": "yahoo_finance",
            "data": {"records": qqq_records},
        },
        {
            "symbol": "GOLD",
            "provider": "alpha_vantage",
            "data": {"Time Series (Daily)": gold_series},
        },
    ]


def create_chart(records: pd.DataFrame, path: Path) -> None:
    """Render a dashboard-style static snapshot."""
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    fig.suptitle("Commodity & ETF Market Intelligence Dashboard", fontsize=18, fontweight="bold")

    for symbol, group in records.groupby("symbol"):
        axes[0, 0].plot(group["ts"], group["close"], label=symbol, linewidth=2)
    anomalies = records[records["is_anomaly"] == 1]
    axes[0, 0].scatter(anomalies["ts"], anomalies["close"], color="#D62728", s=80, label="Anomaly", zorder=5)
    axes[0, 0].set_title("Normalized Close Prices")
    axes[0, 0].set_ylabel("Close")
    axes[0, 0].legend(loc="upper left")

    latest = records.sort_values("ts").groupby("symbol").tail(1).set_index("symbol")
    axes[0, 1].bar(latest.index, latest["close"], color=["#2F80ED", "#27AE60", "#F2994A"])
    axes[0, 1].set_title("Latest Close by Symbol")
    axes[0, 1].set_ylabel("Close")

    wide = records.pivot_table(index="ts", columns="symbol", values="close", aggfunc="last")
    corr = wide.corr()
    image = axes[1, 0].imshow(corr, vmin=-1, vmax=1, cmap="RdYlGn")
    axes[1, 0].set_title("Sample Correlation Matrix")
    axes[1, 0].set_xticks(range(len(corr.columns)), corr.columns)
    axes[1, 0].set_yticks(range(len(corr.index)), corr.index)
    fig.colorbar(image, ax=axes[1, 0], fraction=0.046, pad=0.04)

    volume = records.groupby("symbol")["volume"].mean().sort_values(ascending=False)
    axes[1, 1].barh(volume.index, volume.values, color="#6C5CE7")
    axes[1, 1].set_title("Average Daily Volume")
    axes[1, 1].set_xlabel("Volume")

    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def create_video(records: pd.DataFrame, path: Path) -> None:
    """Create a compact MP4 walkthrough of the generated demo output."""
    width, height = 1280, 720
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 12, (width, height))
    if not writer.isOpened():
        raise RuntimeError("Could not open MP4 writer")

    font_large = ImageFont.truetype("arial.ttf", 44)
    font_medium = ImageFont.truetype("arial.ttf", 28)
    font_small = ImageFont.truetype("arial.ttf", 22)
    symbols = ["SPY", "QQQ", "GOLD"]
    palette = {"SPY": "#2F80ED", "QQQ": "#27AE60", "GOLD": "#F2994A"}

    for frame_index in range(96):
        progress = min(1.0, frame_index / 80)
        image = Image.new("RGB", (width, height), "#F7F9FC")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, width, 86), fill="#101828")
        draw.text((48, 22), "Commodity & ETF Market Intelligence Dashboard", fill="white", font=font_large)

        draw.text((54, 118), "ETL pipeline", fill="#101828", font=font_medium)
        steps = [("Fetch", "#2F80ED"), ("Transform", "#27AE60"), ("Analyze", "#F2994A"), ("Load", "#6C5CE7")]
        for step_index, (label, color) in enumerate(steps):
            x = 72 + step_index * 185
            filled = progress >= (step_index + 1) / len(steps)
            draw.rounded_rectangle((x, 168, x + 138, 222), radius=10, fill=color if filled else "#E4E7EC")
            draw.text((x + 24, 182), label, fill="white" if filled else "#475467", font=font_small)
            if step_index < len(steps) - 1:
                draw.line((x + 148, 195, x + 178, 195), fill="#98A2B3", width=4)

        draw.text((54, 278), "Dashboard signals", fill="#101828", font=font_medium)
        left, top, chart_w, chart_h = 70, 330, 650, 300
        draw.rectangle((left, top, left + chart_w, top + chart_h), fill="white", outline="#D0D5DD")
        visible_count = max(2, int(len(records["ts"].unique()) * progress))
        for symbol in symbols:
            group = records[records["symbol"] == symbol].sort_values("ts").head(visible_count)
            if len(group) < 2:
                continue
            values = group["close"].astype(float).to_numpy()
            min_y = records["close"].min()
            max_y = records["close"].max()
            points = []
            for idx, value in enumerate(values):
                x = left + 24 + int(idx / 29 * (chart_w - 58))
                y = top + chart_h - 24 - int((value - min_y) / (max_y - min_y) * (chart_h - 58))
                points.append((x, y))
            draw.line(points, fill=palette[symbol], width=4)
            draw.text((left + chart_w + 24, top + 18 + symbols.index(symbol) * 34), symbol, fill=palette[symbol], font=font_small)

        summary_x = 800
        latest = records.sort_values("ts").groupby("symbol").tail(1)
        draw.rounded_rectangle((summary_x, 330, 1198, 630), radius=12, fill="white", outline="#D0D5DD")
        draw.text((summary_x + 28, 356), "Sample output", fill="#101828", font=font_medium)
        lines = [
            f"Rows normalized: {len(records)}",
            f"Symbols tracked: {records['symbol'].nunique()}",
            f"Anomalies flagged: {int(records['is_anomaly'].sum())}",
            f"Latest date: {latest['ts'].max().date()}",
        ]
        for line_index, line in enumerate(lines):
            draw.text((summary_x + 30, 418 + line_index * 42), line, fill="#344054", font=font_small)

        frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        writer.write(frame)

    writer.release()


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    transformed = transform_all(build_sample_raw())
    records = detect_anomalies(transformed.records)
    records = records.drop(columns=[column for column in ["rolling_mean", "rolling_std", "iqr_flag"] if column in records.columns])
    records.to_csv(OUTPUT_DIR / "sample_market_data.csv", index=False)

    summary = {
        "status": "success",
        "rows_normalized": int(len(records)),
        "symbols": sorted(records["symbol"].unique().tolist()),
        "anomalies_flagged": int(records["is_anomaly"].sum()),
        "quarantined_rows": int(len(transformed.quarantine)),
        "latest_timestamp": records["ts"].max().isoformat(),
        "artifacts": [
            "output/sample_market_data.csv",
            "output/etl_run_summary.json",
            "output/dashboard_snapshot.png",
            "output/demo_video.mp4",
        ],
    }
    (OUTPUT_DIR / "etl_run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    create_chart(records, OUTPUT_DIR / "dashboard_snapshot.png")
    create_video(records, OUTPUT_DIR / "demo_video.mp4")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
