from __future__ import annotations

from typing import Iterable

from .strategy import ETFCard, MarketState, TradeCard


def print_market(market: MarketState, risk_gate: str) -> None:
    print("\n=== 市场环境 ===")
    print(f"状态: {market.state}")
    print(f"说明: {market.detail}")
    print(f"账户风控: {risk_gate}")


def print_cards(cards: Iterable[TradeCard]) -> None:
    print("\n=== 交易卡片 ===")
    for card in cards:
        print("-" * 72)
        title = f"{card.code} {card.name}".strip()
        print(f"{title} | {card.date} | 评分 {card.score} | 动作: {card.action}")
        print(f"状态: {card.stock_state} | 买点: {card.entry_type} | 收盘: {card.close}")
        print(f"买入区间: {card.buy_zone}")
        print(
            "止损/止盈: "
            f"止损 {fmt(card.stop_price)} | "
            f"一止 {fmt(card.take_profit_1)} | "
            f"二止 {fmt(card.take_profit_2)} | "
            f"移动止盈 {fmt(card.trailing_stop)}"
        )
        print(f"建议仓位: {card.suggested_weight:.1%} | 建议股数: {card.suggested_shares}")
        print(f"风险收益比: {fmt(card.risk_reward)}")
        print(f"理由: {card.reasons}")
        print(f"风险: {card.risks}")


def print_etfs(cards: Iterable[ETFCard]) -> None:
    cards = list(cards)
    if not cards:
        print("\n=== ETF轮动 ===")
        print("未输出ETF候选。可能是未启用，或当前数据源缺少ETF行情。")
        return
    print("\n=== ETF轮动 ===")
    for card in cards:
        print("-" * 72)
        print(f"{card.code} {card.name} | {card.date} | 评分 {card.score} | 动作: {card.action}")
        print(
            f"收盘: {card.close} | 20日涨幅: {card.ret20:.1%} | "
            f"60日涨幅: {card.ret60:.1%} | 20日波动: {card.volatility20:.1%}"
        )
        print(f"建议仓位: {card.suggested_weight:.1%} | 理由: {card.reason}")


def fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)
