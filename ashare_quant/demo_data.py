from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def write_demo_data(base_dir: str | Path = "data/demo") -> Path:
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=180)
    specs = {
        "000300": (3800, 0.0005, 0.009),
        "000905": (5600, 0.0008, 0.012),
        "000852": (5900, 0.0010, 0.015),
        "510300": (3.8, 0.0005, 0.009),
        "510500": (5.6, 0.0008, 0.012),
        "512100": (0.95, 0.0010, 0.015),
        "518880": (5.1, 0.0004, 0.006),
        "600519": (1500, 0.0015, 0.018),
        "000001": (11, 0.0002, 0.012),
        "600036": (38, 0.0007, 0.011),
    }
    rng = np.random.default_rng(20260606)
    for code, (start, drift, vol) in specs.items():
        rets = rng.normal(drift, vol, size=len(dates))
        if code == "600519":
            rets[-25:] += 0.003
            rets[-4] = -0.025
            rets[-1] = 0.025
        if code == "600036":
            rets[-8] = 0.101
            rets[-7:] += rng.normal(-0.002, 0.01, size=7)
        close = start * np.cumprod(1 + rets)
        open_ = close * (1 + rng.normal(0, vol / 3, len(dates)))
        high = np.maximum(open_, close) * (1 + rng.uniform(0.001, vol, len(dates)))
        low = np.minimum(open_, close) * (1 - rng.uniform(0.001, vol, len(dates)))
        volume = rng.integers(200000, 2000000, size=len(dates))
        if code in {"600519", "600036", "000001"}:
            amount = volume * close * 100
        else:
            amount = volume * close * 10
        df = pd.DataFrame(
            {
                "date": dates.strftime("%Y-%m-%d"),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
            }
        )
        df.to_csv(base / f"{code}.csv", index=False)
    return base
