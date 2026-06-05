from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd

from .indicators import normalize_ohlcv


def market_suffix(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("6", "5")):
        return f"{code}.SH"
    return f"{code}.SZ"


def normalize_code(code: str) -> str:
    return str(code).strip().split(".")[0].zfill(6)


@dataclass
class DataProvider:
    name: str

    def stock_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError

    def index_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError


class CSVProvider(DataProvider):
    def __init__(self, csv_dir: str | Path):
        super().__init__("csv")
        self.csv_dir = Path(csv_dir)

    def _read(self, stem: str) -> pd.DataFrame:
        candidates = [
            self.csv_dir / f"{stem}.csv",
            self.csv_dir / f"{normalize_code(stem)}.csv",
        ]
        for path in candidates:
            if path.exists():
                return normalize_ohlcv(pd.read_csv(path))
        raise FileNotFoundError(f"找不到CSV行情文件: {candidates[0]}")

    def stock_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._read(code)

    def index_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._read(code)


class AkShareProvider(DataProvider):
    def __init__(self):
        super().__init__("akshare")
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:
            raise RuntimeError("未安装 akshare。请先安装 akshare，或使用 --provider csv/--demo。") from exc
        self.ak = ak

    def stock_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self.ak.stock_zh_a_hist(
            symbol=normalize_code(code),
            period="daily",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust="qfq",
        )
        return normalize_ohlcv(df)

    def index_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        symbol = f"sh{normalize_code(code)}"
        funcs = [
            ("stock_zh_index_daily_em", {"symbol": symbol}),
            ("index_zh_a_hist", {
                "symbol": normalize_code(code),
                "period": "daily",
                "start_date": start_date.replace("-", ""),
                "end_date": end_date.replace("-", ""),
            }),
        ]
        last_error: Optional[Exception] = None
        for func_name, kwargs in funcs:
            func = getattr(self.ak, func_name, None)
            if func is None:
                continue
            try:
                return normalize_ohlcv(func(**kwargs))
            except Exception as exc:  # AkShare endpoints change occasionally.
                last_error = exc
        raise RuntimeError(f"AkShare无法获取指数 {code}: {last_error}")


class TushareProvider(DataProvider):
    def __init__(self, token: Optional[str] = None):
        super().__init__("tushare")
        try:
            import tushare as ts  # type: ignore
        except ImportError as exc:
            raise RuntimeError("未安装 tushare。请先安装 tushare，或使用 --provider csv/--demo。") from exc
        token = token or os.getenv("TUSHARE_TOKEN")
        if not token:
            raise RuntimeError("使用 tushare 需要设置 TUSHARE_TOKEN 环境变量。")
        ts.set_token(token)
        self.pro = ts.pro_api()

    def stock_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self.pro.daily(
            ts_code=market_suffix(code),
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )
        return self._normalize_tushare(df)

    def index_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self.pro.index_daily(
            ts_code=f"{normalize_code(code)}.SH",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )
        return self._normalize_tushare(df)

    @staticmethod
    def _normalize_tushare(df: pd.DataFrame) -> pd.DataFrame:
        if "trade_date" in df.columns:
            df = df.rename(columns={"trade_date": "date", "vol": "volume"})
        if "amount" in df.columns:
            # Tushare amount unit is usually thousand CNY.
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1000
        return normalize_ohlcv(df)


def build_provider(provider: str, csv_dir: str | Path = "data") -> DataProvider:
    provider = provider.lower()
    if provider == "csv":
        return CSVProvider(csv_dir)
    if provider == "akshare":
        return AkShareProvider()
    if provider == "tushare":
        return TushareProvider()
    if provider == "auto":
        try:
            return AkShareProvider()
        except Exception:
            return TushareProvider()
    raise ValueError(f"未知数据源: {provider}")


def default_date_range(days: int = 220) -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=days * 2)
    return start.isoformat(), end.isoformat()


def load_watchlist(path: str | Path | None, codes: Iterable[str] | None) -> pd.DataFrame:
    rows = []
    if path:
        df = pd.read_csv(path, dtype={"code": str})
        for _, row in df.iterrows():
            rows.append({"code": normalize_code(row["code"]), "name": row.get("name", "")})
    if codes:
        for code in codes:
            rows.append({"code": normalize_code(code), "name": ""})
    if not rows:
        return pd.DataFrame(columns=["code", "name"])
    out = pd.DataFrame(rows).drop_duplicates("code", keep="first")
    return out


def load_positions(path: str | Path | None) -> Dict[str, dict]:
    if not path:
        return {}
    df = pd.read_csv(path, dtype={"code": str})
    positions = {}
    for _, row in df.iterrows():
        code = normalize_code(row["code"])
        positions[code] = row.to_dict()
    return positions


def load_fundamentals(path: str | Path | None) -> Dict[str, dict]:
    if not path:
        return {}
    df = pd.read_csv(path, dtype={"code": str})
    return {normalize_code(row["code"]): row.to_dict() for _, row in df.iterrows()}
