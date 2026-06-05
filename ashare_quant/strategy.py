from __future__ import annotations

from dataclasses import dataclass, asdict
from math import floor
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .data import DataProvider, normalize_code
from .indicators import add_indicators


@dataclass
class MarketState:
    state: str
    allow_new_stock: bool
    detail: str
    benchmark_code: str
    benchmark_ret20: float


@dataclass
class TradeCard:
    code: str
    name: str
    date: str
    market_state: str
    stock_state: str
    score: float
    action: str
    entry_type: str
    close: float
    buy_zone: str
    stop_price: Optional[float]
    take_profit_1: Optional[float]
    take_profit_2: Optional[float]
    trailing_stop: Optional[float]
    suggested_shares: int
    suggested_weight: float
    risk_reward: Optional[float]
    reasons: str
    risks: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ETFCard:
    code: str
    name: str
    date: str
    score: float
    action: str
    close: float
    ret20: float
    ret60: float
    volatility20: float
    suggested_weight: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def is_mainboard_allowed(code: str, config: dict) -> Tuple[bool, str]:
    code = normalize_code(code)
    if not config["universe"].get("allow_mainboard_only", True):
        return True, ""
    for prefix in config["universe"].get("exclude_prefixes", []):
        if code.startswith(str(prefix)):
            return False, f"代码前缀 {prefix} 被排除"
    if not code.startswith(("000", "001", "002", "003", "600", "601", "603", "605")):
        return False, "非默认沪深主板代码"
    return True, ""


def quality_filter(code: str, fundamentals: Dict[str, dict], config: dict) -> Tuple[bool, str, float]:
    q = config.get("quality_filter", {})
    if not q.get("enabled", True):
        return True, "未启用质量过滤", 0.0
    row = fundamentals.get(normalize_code(code))
    if not row:
        return True, "未提供财务数据，仅跳过五因子质量过滤", 0.0

    penalties: List[str] = []
    bonus = 0.0
    roe = _to_float(row.get("roe"))
    debt = _to_float(row.get("debt_ratio"))
    pe = _to_float(row.get("pe_ttm"))
    market_cap = _to_float(row.get("market_cap"))
    if roe is not None:
        bonus += min(max((roe - q.get("min_roe", 0.03)) * 100, -10), 10)
        if roe < q.get("min_roe", 0.03):
            penalties.append("ROE偏低")
    if debt is not None and debt > q.get("max_debt_ratio", 0.75):
        penalties.append("资产负债率偏高")
        bonus -= 5
    if pe is not None and pe > q.get("max_pe_ttm", 120):
        penalties.append("PE过高")
        bonus -= 5
    if market_cap is not None and market_cap < q.get("min_market_cap", 3_000_000_000):
        penalties.append("市值过小，壳价值/流动性风险更高")
        bonus -= 6
    if len(penalties) >= 2:
        return False, "；".join(penalties), bonus
    return True, "；".join(penalties) if penalties else "质量过滤通过", bonus


def evaluate_market(provider: DataProvider, config: dict, start_date: str, end_date: str) -> MarketState:
    states = []
    ret20s = []
    details = []
    benchmark_code = config["market"]["indexes"].get("csi500", "000905")
    benchmark_ret20 = 0.0
    for name, code in config["market"]["indexes"].items():
        try:
            df = add_indicators(provider.index_daily(code, start_date, end_date), config)
            row = df.iloc[-1]
            ma20 = row[f"ma{config['signals']['ma_mid']}"]
            ma60 = row[f"ma{config['signals']['ma_slow']}"]
            close = row["close"]
            ret20 = _safe_float(row.get("ret_20d"), 0.0)
            ret20s.append(ret20)
            if code == benchmark_code:
                benchmark_ret20 = ret20
            strong = close > ma20 and ma20 > ma60
            weak = close < ma60 and ma20 < ma60
            states.append("strong" if strong else "weak" if weak else "neutral")
            details.append(f"{name}:{'强' if strong else '弱' if weak else '震荡'}")
        except Exception as exc:
            details.append(f"{name}:获取失败({exc})")

    strong_count = states.count("strong")
    weak_count = states.count("weak")
    if weak_count >= config["market"].get("weak_requires_at_least", 2):
        state = "弱势"
        allow = False
    elif strong_count >= config["market"].get("strong_requires_at_least", 2):
        state = "强势"
        allow = True
    else:
        state = "震荡"
        allow = True
    if not ret20s:
        benchmark_ret20 = 0.0
    elif benchmark_ret20 == 0.0:
        benchmark_ret20 = float(np.nanmean(ret20s))
    return MarketState(state, allow, "，".join(details), benchmark_code, benchmark_ret20)


def analyze_stock(
    code: str,
    name: str,
    provider: DataProvider,
    config: dict,
    market: MarketState,
    start_date: str,
    end_date: str,
    position: Optional[dict] = None,
    fundamentals: Optional[Dict[str, dict]] = None,
) -> TradeCard:
    code = normalize_code(code)
    fundamentals = fundamentals or {}
    allowed, filter_reason = is_mainboard_allowed(code, config)
    if not allowed:
        return _blocked_card(code, name, market.state, filter_reason)

    raw = provider.stock_daily(code, start_date, end_date)
    df = add_indicators(raw, config)
    row = df.iloc[-1]
    date = row["date"].date().isoformat()

    if len(df) < config["universe"]["min_history_days"]:
        return _blocked_card(code, name, market.state, "历史数据不足", date, _safe_float(row["close"]))
    if row["close"] < config["universe"]["min_price"]:
        return _blocked_card(code, name, market.state, "股价低于最低价格过滤线", date, _safe_float(row["close"]))
    if _safe_float(row["avg_amount_20"]) < config["universe"]["min_avg_amount_20d"]:
        return _blocked_card(code, name, market.state, "近20日日均成交额不足", date, _safe_float(row["close"]))

    q_ok, q_reason, q_bonus = quality_filter(code, fundamentals, config)
    if not q_ok:
        return _blocked_card(code, name, market.state, f"五因子质量过滤未通过: {q_reason}", date, _safe_float(row["close"]))

    trend_score, trend_reasons = _score_trend(row, config)
    rs_score, rs_reason = _score_relative_strength(row, market)
    vol_score, vol_reason = _score_volume(row, config)
    entry_type, entry_score, entry_reason, stock_state = _entry_signal(df, config, market)
    first_board_bonus, first_board_reason = _first_board_pullback(df, config)
    if first_board_bonus > entry_score:
        entry_type = "首板回调"
        entry_score = first_board_bonus
        entry_reason = first_board_reason
        stock_state = "首板回调观察"

    stop_price = _stop_price(df, config, entry_type)
    close = _safe_float(row["close"])
    risk = close - stop_price if stop_price else None
    target = close + max(close * config["signals"]["take_profit_r1_pct"], risk or 0)
    rr_score, risk_reward, rr_reason = _score_risk_reward(close, stop_price, target, config)

    total_score = trend_score + rs_score + vol_score + entry_score + rr_score + q_bonus
    total_score = max(0.0, min(100.0, total_score))

    trailing_stop = _trailing_stop(df, config, position)
    action, action_reason = _decide_action(total_score, entry_type, market, position, df, stop_price, trailing_stop, config)
    suggested_weight, suggested_shares = _position_size(close, stop_price, total_score, entry_type, config, market, position)

    take_profit_1 = close + (risk if risk and risk > 0 else close * config["signals"]["take_profit_r1_pct"])
    take_profit_2 = close + (2 * risk if risk and risk > 0 else close * config["signals"]["take_profit_r2_pct"])
    reasons = "；".join([r for r in [trend_reasons, rs_reason, vol_reason, entry_reason, rr_reason, q_reason, action_reason] if r])
    risks = _risk_text(df, config, market, position)
    buy_zone = _buy_zone(close, entry_type)

    return TradeCard(
        code=code,
        name=name,
        date=date,
        market_state=market.state,
        stock_state=stock_state,
        score=round(total_score, 1),
        action=action,
        entry_type=entry_type,
        close=round(close, 3),
        buy_zone=buy_zone,
        stop_price=_round_or_none(stop_price),
        take_profit_1=_round_or_none(take_profit_1),
        take_profit_2=_round_or_none(take_profit_2),
        trailing_stop=_round_or_none(trailing_stop),
        suggested_shares=suggested_shares,
        suggested_weight=round(suggested_weight, 4),
        risk_reward=_round_or_none(risk_reward),
        reasons=reasons,
        risks=risks,
    )


def account_risk_gate(config: dict) -> str:
    equity = float(config["profile"].get("account_equity", 0) or 0)
    peak = float(config["profile"].get("peak_equity", equity) or equity)
    if peak <= 0:
        return "未设置账户净值，按正常风控处理"
    drawdown = max(0.0, (peak - equity) / peak)
    r = config["risk"]
    if drawdown >= r["full_stop_at_drawdown"]:
        return f"账户回撤 {drawdown:.1%}，触发清仓暂停线"
    if drawdown >= r["stop_stock_trading_at_drawdown"]:
        return f"账户回撤 {drawdown:.1%}，停止新增个股交易"
    if drawdown >= r["half_exposure_at_drawdown"]:
        return f"账户回撤 {drawdown:.1%}，总仓位应降到50%以内"
    if drawdown >= r["reduce_new_position_at_drawdown"]:
        return f"账户回撤 {drawdown:.1%}，新开仓仓位减半"
    return f"账户回撤 {drawdown:.1%}，风控正常"


def analyze_etf_rotation(provider: DataProvider, config: dict, start_date: str, end_date: str) -> List[ETFCard]:
    etf_cfg = config.get("etf_rotation", {})
    if not etf_cfg.get("enabled", True):
        return []
    cards: List[ETFCard] = []
    for code, name in etf_cfg.get("candidates", {}).items():
        try:
            df = add_indicators(provider.stock_daily(code, start_date, end_date), config)
            row = df.iloc[-1]
            ma20 = row[f"ma{config['signals']['ma_mid']}"]
            ret20 = _safe_float(row.get("ret_20d"), 0.0)
            ret60 = _safe_float(row.get("ret_60d"), 0.0)
            vol20 = _safe_float(row.get("volatility_20"), 0.0)
            score = ret20 * 0.5 + ret60 * 0.3 - vol20 * 0.2
            above_ma20 = row["close"] > ma20
            if etf_cfg.get("require_above_ma20", True) and not above_ma20:
                action = "观望"
                reason = "低于MA20"
                suggested_weight = 0.0
            else:
                action = "候选"
                reason = "满足ETF轮动趋势过滤"
                suggested_weight = etf_cfg["max_total_weight"] / max(1, etf_cfg["top_n"])
            cards.append(
                ETFCard(
                    code=normalize_code(code),
                    name=name,
                    date=row["date"].date().isoformat(),
                    score=round(float(score) * 100, 2),
                    action=action,
                    close=round(float(row["close"]), 3),
                    ret20=round(ret20, 4),
                    ret60=round(ret60, 4),
                    volatility20=round(vol20, 4),
                    suggested_weight=round(suggested_weight, 4),
                    reason=reason,
                )
            )
        except Exception:
            continue
    tradable = [c for c in cards if c.action == "候选"]
    tradable = sorted(tradable, key=lambda c: c.score, reverse=True)
    selected_codes = {c.code for c in tradable[: etf_cfg.get("top_n", 2)]}
    out = []
    for card in sorted(cards, key=lambda c: c.score, reverse=True):
        if card.code in selected_codes:
            card.action = "可配置"
        elif card.action == "候选":
            card.action = "备选"
            card.suggested_weight = 0.0
        out.append(card)
    return out


def _score_trend(row: pd.Series, config: dict) -> Tuple[float, str]:
    s = config["signals"]
    close = row["close"]
    ma10 = row[f"ma{s['ma_fast']}"]
    ma20 = row[f"ma{s['ma_mid']}"]
    ma60 = row[f"ma{s['ma_slow']}"]
    score = 0.0
    reasons = []
    if close > ma20:
        score += 9
        reasons.append("收盘价在MA20上方")
    if ma20 > ma60:
        score += 10
        reasons.append("MA20高于MA60")
    if close > ma10:
        score += 5
    if row.get("ret_20d", 0) > 0:
        score += 6
    if row.get("ret_60d", 0) > 0:
        score += 5
    return min(score, 35), "、".join(reasons) or "趋势未确认"


def _score_relative_strength(row: pd.Series, market: MarketState) -> Tuple[float, str]:
    ret20 = _safe_float(row.get("ret_20d"), 0.0)
    ret60 = _safe_float(row.get("ret_60d"), 0.0)
    score = 0.0
    if ret20 > market.benchmark_ret20:
        score += 12
    if ret20 > 0.05:
        score += 5
    if ret60 > 0:
        score += 3
    return min(score, 20), f"20日相对强弱 {ret20 - market.benchmark_ret20:.1%}"


def _score_volume(row: pd.Series, config: dict) -> Tuple[float, str]:
    ratio = _safe_float(row.get("volume_ratio"), 0.0)
    if ratio >= config["signals"]["breakout_volume_ratio"]:
        return 15, f"成交量放大 {ratio:.2f}倍"
    if 0.8 <= ratio < config["signals"]["breakout_volume_ratio"]:
        return 8, f"成交量温和 {ratio:.2f}倍"
    return 3, f"成交量不足 {ratio:.2f}倍"


def _entry_signal(df: pd.DataFrame, config: dict, market: MarketState) -> Tuple[str, float, str, str]:
    row = df.iloc[-1]
    prev = df.iloc[-2]
    s = config["signals"]
    close = row["close"]
    ma10 = row[f"ma{s['ma_fast']}"]
    ma20 = row[f"ma{s['ma_mid']}"]
    ma60 = row[f"ma{s['ma_slow']}"]
    breakout = close > row["prev_high_20"] and row["volume_ratio"] >= s["breakout_volume_ratio"]
    not_over_chased = _safe_float(row.get("ret_5d"), 0.0) <= s["max_5d_chase_return"]
    if breakout and close > ma20 > ma60 and not_over_chased and market.state == "强势":
        return "趋势突破", 15, "突破20日高点且放量", "突破"

    near_ma = min(abs(close - ma10) / close, abs(close - ma20) / close) <= s["pullback_near_ma_pct"]
    previous_pullback = prev["close"] < prev[f"ma{s['ma_fast']}"] or prev["ret_1d"] < 0
    confirm = close > ma10 or close > prev["high"]
    volume_ok = row["volume_ratio"] >= s["pullback_confirm_volume_ratio"] or row["volume"] > prev["volume"]
    if close > ma60 and ma20 >= df[f"ma{s['ma_mid']}"].iloc[-5] and near_ma and previous_pullback and confirm and volume_ok:
        return "趋势回踩", 15, "回踩MA10/MA20后重新确认", "回踩确认"

    if close > ma20 > ma60:
        return "等待买点", 6, "趋势存在但买点尚未触发", "强趋势"
    if close < ma20:
        return "无买点", 1, "收盘价低于MA20", "破位/观望"
    return "无买点", 3, "信号不完整", "观望"


def _first_board_pullback(df: pd.DataFrame, config: dict) -> Tuple[float, str]:
    fb = config.get("first_board_pullback", {})
    if not fb.get("enabled", False) or len(df) < 30:
        return 0.0, ""
    recent = df.tail(fb["max_days_after_board"] + 1).copy()
    limit_positions = recent.index[recent["limit_up"]].tolist()
    if not limit_positions:
        return 0.0, ""
    board_idx = limit_positions[-1]
    days_after = int(df.index[-1] - board_idx)
    if days_after < fb["min_days_after_board"] or days_after > fb["max_days_after_board"]:
        return 0.0, ""
    before = df.loc[: board_idx - 1].tail(fb["lookback_no_limit_up_days"])
    if bool(before["limit_up"].any()):
        return 0.0, ""
    board = df.loc[board_idx]
    row = df.iloc[-1]
    pullback = (board["close"] - row["close"]) / board["close"]
    if pullback < fb["min_pullback_pct"] or pullback > fb["max_pullback_pct"]:
        return 0.0, ""
    if row["close"] < board["low"] * (1 - fb["max_break_board_low_pct"]):
        return 0.0, ""
    if fb.get("require_volume_shrink", True) and row["volume"] >= board["volume"]:
        return 0.0, ""
    return 15.0, f"首板后第{days_after}日回调，回撤{pullback:.1%}且未破首板低点"


def _stop_price(df: pd.DataFrame, config: dict, entry_type: str) -> Optional[float]:
    row = df.iloc[-1]
    s = config["signals"]
    hard = row["close"] * (1 - config["risk"]["hard_stop_loss_pct"])
    atr_stop = row["close"] - s["trailing_atr_multiple"] * row["atr"] if not np.isnan(row["atr"]) else hard
    if entry_type == "趋势回踩":
        recent_low = df.tail(8)["low"].min() * 0.99
        ma_stop = row[f"ma{s['ma_mid']}"] * 0.99
        return max(recent_low, ma_stop, atr_stop, hard)
    if entry_type == "趋势突破":
        breakout_low = row["low"]
        return max(breakout_low, atr_stop, hard)
    if entry_type == "首板回调":
        return max(df.tail(8)["low"].min() * 0.99, atr_stop, hard)
    return max(atr_stop, hard)


def _score_risk_reward(close: float, stop: Optional[float], target: float, config: dict) -> Tuple[float, Optional[float], str]:
    if not stop or stop >= close:
        return 0.0, None, "止损价无效"
    stop_dist = (close - stop) / close
    if stop_dist > config["risk"]["max_stop_distance_pct"]:
        return 0.0, None, f"止损空间过大 {stop_dist:.1%}"
    rr = (target - close) / (close - stop)
    if rr >= 2:
        return 15.0, rr, f"风险收益比 {rr:.2f}"
    if rr >= 1.2:
        return 9.0, rr, f"风险收益比 {rr:.2f}"
    return 4.0, rr, f"风险收益比偏低 {rr:.2f}"


def _trailing_stop(df: pd.DataFrame, config: dict, position: Optional[dict]) -> Optional[float]:
    row = df.iloc[-1]
    s = config["signals"]
    atr_stop = row["close"] - s["trailing_atr_multiple"] * row["atr"] if not np.isnan(row["atr"]) else None
    ma_stop = row[f"ma{s['ma_fast']}"]
    stops = [x for x in [atr_stop, ma_stop] if x and not np.isnan(x)]
    if position and _to_float(position.get("highest_close")):
        stops.append(_to_float(position.get("highest_close")) - s["trailing_atr_multiple"] * row["atr"])
    return max(stops) if stops else None


def _decide_action(
    score: float,
    entry_type: str,
    market: MarketState,
    position: Optional[dict],
    df: pd.DataFrame,
    stop: Optional[float],
    trailing_stop: Optional[float],
    config: dict,
) -> Tuple[str, str]:
    row = df.iloc[-1]
    close = row["close"]
    if position:
        buy_price = _to_float(position.get("buy_price")) or close
        hold_days = _holding_days(position, row["date"])
        if stop and close <= stop:
            return "卖出", "触发初始/技术止损"
        if trailing_stop and close <= trailing_stop:
            return "减仓/卖出", "触发移动止盈"
        if close >= buy_price * (1 + config["signals"]["take_profit_r2_pct"]):
            return "减仓", "达到第二止盈区"
        if close >= buy_price * (1 + config["signals"]["take_profit_r1_pct"]):
            return "减仓1/3", "达到第一止盈区"
        if hold_days >= config["profile"]["max_holding_days"]:
            return "卖出/换仓", "达到最大持有天数"
        if hold_days >= config["signals"]["stale_position_days"] and close <= buy_price * 1.02:
            return "卖出/观察", "持有多日未形成有效浮盈"
        return "持有", "持仓未触发退出"

    gate = account_risk_gate(config)
    if "清仓" in gate or "停止新增" in gate:
        return "观望", gate
    if not market.allow_new_stock:
        return "观望", "市场弱势，不新开个股仓"
    if score >= 80 and entry_type in ("趋势突破", "趋势回踩"):
        return "可买入", "评分达到重点交易区"
    if score >= 70 and entry_type == "首板回调":
        return "小仓试验", "首板回调仅限小仓位"
    if score >= 70:
        return "观察", "评分接近买入线，等待次日价格确认"
    return "观望", "评分不足"


def _position_size(
    close: float,
    stop: Optional[float],
    score: float,
    entry_type: str,
    config: dict,
    market: MarketState,
    position: Optional[dict],
) -> Tuple[float, int]:
    if position or not stop or stop >= close or not market.allow_new_stock:
        return 0.0, 0
    if entry_type not in ("趋势突破", "趋势回踩", "首板回调"):
        return 0.0, 0
    action_allowed = score >= 70 if entry_type == "首板回调" else score >= 80
    if not action_allowed:
        return 0.0, 0
    equity = float(config["profile"].get("account_equity", 0) or 0)
    if equity <= 0:
        return 0.0, 0
    risk_cash = equity * config["risk"]["risk_per_trade"]
    shares_by_risk = floor(risk_cash / (close - stop) / 100) * 100
    max_weight = config["risk"]["max_single_stock_weight"]
    if entry_type == "首板回调":
        max_weight = min(max_weight, config["first_board_pullback"]["max_weight"])
    max_cash = equity * max_weight
    shares_by_weight = floor(max_cash / close / 100) * 100
    shares = max(0, min(shares_by_risk, shares_by_weight))
    weight = shares * close / equity if equity else 0.0
    return weight, int(shares)


def _risk_text(df: pd.DataFrame, config: dict, market: MarketState, position: Optional[dict]) -> str:
    row = df.iloc[-1]
    risks = []
    if market.state == "震荡":
        risks.append("市场震荡，避免追高")
    if market.state == "弱势":
        risks.append("市场弱势")
    if row["volume_ratio"] < 0.8:
        risks.append("成交量不足")
    if row["limit_up"]:
        risks.append("当日涨停，次日成交和高开风险较高")
    if _safe_float(row.get("ret_5d"), 0.0) > config["signals"]["max_5d_chase_return"]:
        risks.append("近5日涨幅偏高")
    if position:
        risks.append("已有持仓，优先执行卖点和仓位纪律")
    return "；".join(risks) if risks else "未见主要规则风险"


def _buy_zone(close: float, entry_type: str) -> str:
    if entry_type == "趋势突破":
        return f"{close:.2f} 附近；次日高开超过3%-5%不追"
    if entry_type == "趋势回踩":
        return f"{close * 0.995:.2f}-{close * 1.015:.2f}"
    if entry_type == "首板回调":
        return f"{close * 0.99:.2f}-{close * 1.01:.2f}，仅小仓"
    return "无"


def _blocked_card(code: str, name: str, market_state: str, reason: str, date: str = "", close: float = 0.0) -> TradeCard:
    return TradeCard(
        code=normalize_code(code),
        name=name,
        date=date,
        market_state=market_state,
        stock_state="过滤",
        score=0.0,
        action="不分析",
        entry_type="无",
        close=round(close, 3),
        buy_zone="无",
        stop_price=None,
        take_profit_1=None,
        take_profit_2=None,
        trailing_stop=None,
        suggested_shares=0,
        suggested_weight=0.0,
        risk_reward=None,
        reasons=reason,
        risks=reason,
    )


def _holding_days(position: dict, current_date: pd.Timestamp) -> int:
    buy_date = position.get("buy_date")
    if not buy_date:
        return 0
    try:
        return int(np.busday_count(pd.to_datetime(buy_date).date(), current_date.date()))
    except Exception:
        return 0


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _to_float(value) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _round_or_none(value: Optional[float]) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 3)
