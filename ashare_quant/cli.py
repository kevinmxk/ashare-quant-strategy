from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import List

import pandas as pd

from .config import load_config
from .data import build_provider, default_date_range, load_fundamentals, load_positions, load_watchlist
from .demo_data import write_demo_data
from .formatting import print_cards, print_etfs, print_market
from .strategy import account_risk_gate, analyze_etf_rotation, analyze_stock, evaluate_market


def main() -> None:
    parser = argparse.ArgumentParser(description="A股主板短线趋势交易辅助策略 V1")
    parser.add_argument("--config", default="config/default.yaml", help="策略配置文件")
    parser.add_argument("--provider", default="csv", choices=["csv", "akshare", "tushare", "auto"], help="数据源")
    parser.add_argument("--csv-dir", default="data", help="CSV行情目录")
    parser.add_argument("--watchlist", default=None, help="自选股CSV，字段: code,name")
    parser.add_argument("--codes", default=None, help="逗号分隔股票代码，如 600519,000001")
    parser.add_argument("--positions", default=None, help="持仓CSV，字段: code,name,buy_date,buy_price,shares,highest_close")
    parser.add_argument("--fundamentals", default=None, help="可选财务CSV，字段: code,roe,debt_ratio,pe_ttm,market_cap")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--equity", type=float, default=None, help="当前账户权益")
    parser.add_argument("--peak-equity", type=float, default=None, help="账户历史高点权益")
    parser.add_argument("--output", default=None, help="输出CSV路径")
    parser.add_argument("--demo", action="store_true", help="生成并使用离线演示数据")
    parser.add_argument("--interactive", action="store_true", help="命令行交互输入")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.interactive:
        args = _interactive(args)

    if args.equity is not None:
        config["profile"]["account_equity"] = args.equity
    if args.peak_equity is not None:
        config["profile"]["peak_equity"] = args.peak_equity

    if args.demo:
        demo_dir = write_demo_data()
        args.provider = "csv"
        args.csv_dir = str(demo_dir)
        args.watchlist = args.watchlist or "examples/watchlist.csv"
        print(f"已生成离线演示数据: {demo_dir}")

    start_date, end_date = args.start, args.end
    if not start_date or not end_date:
        start_date, end_date = default_date_range()

    codes = _split_codes(args.codes)
    watchlist = load_watchlist(args.watchlist, codes)
    if watchlist.empty:
        raise SystemExit("请通过 --codes 或 --watchlist 提供候选股票。")

    provider = build_provider(args.provider, args.csv_dir)
    positions = load_positions(args.positions)
    fundamentals = load_fundamentals(args.fundamentals)

    market = evaluate_market(provider, config, start_date, end_date)
    print_market(market, account_risk_gate(config))

    cards = []
    for _, item in watchlist.iterrows():
        try:
            card = analyze_stock(
                code=item["code"],
                name=item.get("name", ""),
                provider=provider,
                config=config,
                market=market,
                start_date=start_date,
                end_date=end_date,
                position=positions.get(str(item["code"]).zfill(6)),
                fundamentals=fundamentals,
            )
        except Exception as exc:
            card = _error_card(item["code"], item.get("name", ""), market.state, str(exc))
        cards.append(card)

    cards = sorted(cards, key=lambda c: c.score, reverse=True)
    print_cards(cards)

    etf_cards = analyze_etf_rotation(provider, config, start_date, end_date)
    print_etfs(etf_cards)

    output = args.output
    if output is None:
        Path("reports").mkdir(exist_ok=True)
        output = f"reports/signals_{date.today().isoformat()}.csv"
    pd.DataFrame([c.to_dict() for c in cards]).to_csv(output, index=False, encoding="utf-8-sig")
    if etf_cards:
        etf_output = str(Path(output).with_name(Path(output).stem + "_etf.csv"))
        pd.DataFrame([c.to_dict() for c in etf_cards]).to_csv(etf_output, index=False, encoding="utf-8-sig")
        print(f"已保存ETF表: {etf_output}")
    print(f"\n已保存信号表: {output}")
    print("提示: 本工具只做交易辅助，不构成投资建议；下单前请人工确认成交、涨跌停、公告和流动性。")


def _interactive(args: argparse.Namespace) -> argparse.Namespace:
    print("进入交互模式。直接回车会保留默认值。")
    provider = input(f"数据源 csv/akshare/tushare/auto [{args.provider}]: ").strip()
    if provider:
        args.provider = provider
    if args.provider == "csv":
        csv_dir = input(f"CSV目录 [{args.csv_dir}]: ").strip()
        if csv_dir:
            args.csv_dir = csv_dir
    codes = input("候选股票代码，逗号分隔: ").strip()
    if codes:
        args.codes = codes
    watchlist = input("自选股CSV路径，可空: ").strip()
    if watchlist:
        args.watchlist = watchlist
    equity = input("当前账户权益，可空: ").strip()
    if equity:
        args.equity = float(equity)
    peak = input("账户历史高点权益，可空: ").strip()
    if peak:
        args.peak_equity = float(peak)
    return args


def _split_codes(codes: str | None) -> List[str]:
    if not codes:
        return []
    return [c.strip() for c in codes.split(",") if c.strip()]


def _error_card(code: str, name: str, market_state: str, message: str):
    from .strategy import TradeCard

    return TradeCard(
        code=str(code).zfill(6),
        name=name,
        date="",
        market_state=market_state,
        stock_state="错误",
        score=0,
        action="不分析",
        entry_type="无",
        close=0,
        buy_zone="无",
        stop_price=None,
        take_profit_1=None,
        take_profit_2=None,
        trailing_stop=None,
        suggested_shares=0,
        suggested_weight=0,
        risk_reward=None,
        reasons=message,
        risks=message,
    )


if __name__ == "__main__":
    main()
