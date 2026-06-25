"""APScheduler runner with a Flask health endpoint for ETL monitoring."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify
from loguru import logger
import yaml

from commodity_etf_dashboard.etl import pipeline
from commodity_etf_dashboard.etl.fetcher import expand_env_vars


PROJECT_ROOT = Path(__file__).resolve().parents[1]
app = Flask(__name__)
state: dict[str, Any] = {
    "last_run": None,
    "next_run": None,
    "last_duration_sec": None,
    "last_status": None,
}
scheduler_ref: BackgroundScheduler | None = None


def run_pipeline_job() -> None:
    """Run ETL once while shielding the scheduler from job failures."""
    try:
        result = pipeline.run()
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        state["last_duration_sec"] = round(float(result["duration_sec"]), 3)
        state["last_status"] = result["status"]
        _refresh_next_run()
        logger.bind(**result).info("scheduled_pipeline_completed")
    except Exception as exc:
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        state["last_status"] = "failed"
        _refresh_next_run()
        logger.bind(error=str(exc)).error("scheduled_pipeline_failed")


@app.route("/health")
def health() -> Any:
    """Return scheduler health details."""
    return jsonify(
        {
            "status": "ok",
            "last_run": state["last_run"],
            "next_run": state["next_run"],
            "last_duration_sec": state["last_duration_sec"],
        }
    )


def create_scheduler(interval_minutes: int) -> BackgroundScheduler:
    """Create and start the 15-minute ETL scheduler."""
    global scheduler_ref
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_pipeline_job,
        "cron",
        minute=f"*/{interval_minutes}",
        second=0,
        id="commodity_etf_pipeline",
        replace_existing=True,
    )
    scheduler.start()
    scheduler_ref = scheduler
    _refresh_next_run()
    logger.bind(next_run=state["next_run"]).info("scheduler_started")
    return scheduler


def _refresh_next_run() -> None:
    if scheduler_ref is None:
        return
    job = scheduler_ref.get_job("commodity_etf_pipeline")
    state["next_run"] = job.next_run_time.isoformat() if job and job.next_run_time else None
    logger.bind(next_run=state["next_run"]).info("scheduler_next_run")


def load_settings() -> dict[str, Any]:
    """Read scheduler settings from config.yaml."""
    with (PROJECT_ROOT / "config" / "config.yaml").open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    return {
        "interval_minutes": int(expand_env_vars(str(config["scheduler"]["refresh_interval_minutes"]))),
        "health_port": int(expand_env_vars(str(config["scheduler"]["health_port"]))),
    }


if __name__ == "__main__":
    settings = load_settings()
    scheduler_instance = create_scheduler(settings["interval_minutes"])
    try:
        app.run(host="0.0.0.0", port=settings["health_port"])
    finally:
        scheduler_instance.shutdown(wait=False)
