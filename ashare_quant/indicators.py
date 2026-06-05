from __future__ import annotations

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    lower_map = {str(c).strip().lower(): c for c in out.columns}
    rename = {}
    aliases = {
        "date": ["date", "日期", "trade_date"],
        "open": ["open", "开盘"],
        "high": ["high", "最高"],
        "low": ["low", "最低"],
        "close": ["close", "收盘"],
        "volume": ["volume", "vol", "成交量"],
        "amount": ["amount", "成交额"],
    }
    for target, names in aliases.items():
        for name in names:
            if name in out.columns:
                rename[name] = target
                break
            if name.lower() in lower_map:
                rename[lower_map[name.lower()]] = target
                break
    out = out.rename(columns=rename)
    missing = [c for c in REQUIRED_COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(f"行情数据缺少字段: {missing}")

    out = out[REQUIRED_COLUMNS].copy()
    out["date"] = pd.to_datetime(out["date"])
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date", "open", "high", "low", "close"])
    out = out.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    out["volume"] = out["volume"].fillna(0)
    out["amount"] = out["amount"].fillna(0)
    return out


def add_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    s = config["signals"]
    out = normalize_ohlcv(df)
    close = out["close"]
    high = out["high"]
    low = out["low"]
    prev_close = close.shift(1)

    for window in [s["ma_fast"], s["ma_mid"], s["ma_slow"]]:
        out[f"ma{window}"] = close.rolling(window).mean()

    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.rolling(s["atr_window"]).mean()
    out["ret_1d"] = close.pct_change()
    out["ret_5d"] = close.pct_change(5)
    out["ret_20d"] = close.pct_change(20)
    out["ret_60d"] = close.pct_change(60)
    out["high_20"] = high.rolling(s["breakout_window"]).max()
    out["prev_high_20"] = out["high_20"].shift(1)
    out["avg_volume_20"] = out["volume"].rolling(s["volume_window"]).mean()
    out["avg_amount_20"] = out["amount"].rolling(20).mean()
    out["volume_ratio"] = np.where(out["avg_volume_20"] > 0, out["volume"] / out["avg_volume_20"], np.nan)
    out["volatility_20"] = out["ret_1d"].rolling(20).std()
    out["limit_up"] = close >= prev_close * 1.098
    out["limit_down"] = close <= prev_close * 0.902
    return out


def last_row(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        raise ValueError("行情数据为空")
    return df.iloc[-1]
