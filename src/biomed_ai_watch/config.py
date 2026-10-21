from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_config(path: Path | None = None) -> dict:
    with open(path or ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def week_window(cfg: dict, end: date | None = None) -> tuple[date, date]:
    end = end or date.today()
    return end - timedelta(days=cfg.get("lookback_days", 7)), end
