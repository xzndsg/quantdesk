from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from .market import calculate_atr, calculate_rsi
from .models import (
    BacktestResult,
    MarketBundle,
    NewsContext,
    RiskCheck,
    RiskReport,
    StrategySpec,
    TradeSignal,
)


RISK_CAP = {"保守": (0.10, 15), "稳健": (0.20, 20), "积极": (0.30, 30)}


def evaluate_risk(
    market: MarketBundle,
    news: NewsContext,
    backtest: BacktestResult,
    spec: StrategySpec,
    risk_level: str,
) -> RiskReport:
    position_cap, drawdown_cap = RISK_CAP[risk_level]
    position_pct = min(position_cap, spec.max_position_pct)
    checks: list[RiskCheck] = []

    history_rows = len(market.history)
    checks.append(
        RiskCheck(
            name="数据完整性",
            status="PASS" if history_rows >= 250 else "BLOCK",
            detail=f"有效日线 {history_rows} 条，至少要求 250 条",
        )
    )
    try:
        stale_days = (datetime.now().date() - date.fromisoformat(market.data_as_of)).days
    except ValueError:
        stale_days = 999
    checks.append(
        RiskCheck(
            name="数据时效性",
            status="PASS" if stale_days <= 14 else "BLOCK",
            detail=f"最新行情距当前 {stale_days} 个自然日",
        )
    )
    checks.append(
        RiskCheck(
            name="留出集交易样本",
            status="PASS" if backtest.trade_count >= 1 else "BLOCK",
            detail=f"完整平仓交易 {backtest.trade_count} 笔",
        )
    )
    checks.append(
        RiskCheck(
            name="最大回撤",
            status="PASS" if backtest.max_drawdown_pct <= drawdown_cap else "BLOCK",
            detail=f"回撤 {backtest.max_drawdown_pct:.2f}%，{risk_level}上限 {drawdown_cap}%",
        )
    )
    checks.append(
        RiskCheck(
            name="留出集收益",
            status="PASS" if backtest.total_return_pct > 0 else "WARN",
            detail=f"留出集收益率 {backtest.total_return_pct:.2f}%",
        )
    )
    checks.append(
        RiskCheck(
            name="留出集夏普",
            status="PASS" if backtest.sharpe >= 0 else "WARN",
            detail=f"夏普比率 {backtest.sharpe:.2f}",
        )
    )

    average_amount = market.summary.get("avg_amount_20d")
    checks.append(
        RiskCheck(
            name="流动性",
            status="PASS" if average_amount and average_amount >= 50_000_000 else "WARN",
            detail=(
                f"20 日平均成交额 {average_amount / 100_000_000:.2f} 亿元"
                if average_amount
                else "成交额数据不足"
            ),
        )
    )
    negative_news = news.score < -0.5
    checks.append(
        RiskCheck(
            name="新闻风险",
            status="WARN" if negative_news else "PASS",
            detail=f"新闻评分 {news.score:.2f}；{news.summary}",
        )
    )

    blocked = any(check.status == "BLOCK" for check in checks)
    backtest_warning = backtest.total_return_pct <= 0 or backtest.sharpe < 0
    other_warning = any(
        check.status == "WARN" and check.name not in {"留出集收益", "留出集夏普", "新闻风险"}
        for check in checks
    )
    if blocked:
        status = "BLOCK"
        position_pct = 0
        summary = "存在硬性风险阻断项，不输出买入建议；持仓退出信号仍可执行。"
    elif backtest_warning or other_warning:
        status = "WATCH"
        position_pct = 0
        summary = "验证表现或交易条件不足，建议观望。"
    elif negative_news:
        status = "REDUCE"
        position_pct = round(position_pct / 2, 4)
        summary = "存在显著负面新闻，仅在技术信号满足时以减半仓位参与。"
    else:
        status = "PASS"
        summary = "风险检查通过，仍须等待策略触发条件。"
    return RiskReport(status=status, position_pct=position_pct, checks=checks, summary=summary)


def generate_signal(
    market: MarketBundle,
    spec: StrategySpec,
    risk: RiskReport,
) -> TradeSignal:
    history = market.history.copy()
    close = history["close"]
    fast = close.rolling(spec.fast_window).mean()
    slow = close.rolling(spec.slow_window).mean()
    rsi = calculate_rsi(close, spec.rsi_period)
    atr = calculate_atr(history, spec.rsi_period)
    volume_ma = history["volume"].rolling(20).mean()
    lower_band = fast - 2 * close.rolling(spec.fast_window).std(ddof=0)

    latest_close = float(close.iloc[-1])
    latest_atr = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else latest_close * 0.03
    required = [fast.iloc[-1], slow.iloc[-1], rsi.iloc[-1], volume_ma.iloc[-1]]
    if any(pd.isna(value) for value in required):
        raw_action = "watch"
    elif spec.strategy_type == "trend":
        entry = (
            latest_close > fast.iloc[-1]
            and fast.iloc[-1] > slow.iloc[-1]
            and rsi.iloc[-1] < spec.rsi_overbought
            and (not spec.volume_filter or history["volume"].iloc[-1] >= volume_ma.iloc[-1])
        )
        exit_signal = latest_close < fast.iloc[-1]
        raw_action = "conditional_buy" if entry else ("sell" if exit_signal else "watch")
    else:
        entry = (
            latest_close < lower_band.iloc[-1]
            and rsi.iloc[-1] < spec.rsi_oversold
            and (not spec.volume_filter or history["volume"].iloc[-1] >= volume_ma.iloc[-1])
        )
        exit_signal = latest_close > fast.iloc[-1] or rsi.iloc[-1] > 50
        raw_action = "conditional_buy" if entry else ("sell" if exit_signal else "watch")

    if raw_action == "sell":
        action = "sell"
    elif risk.status == "BLOCK":
        action = "blocked"
    elif risk.status == "WATCH":
        action = "watch"
    else:
        action = raw_action

    if spec.strategy_type == "trend":
        entry_condition = (
            f"收盘价 > MA{spec.fast_window}，且 MA{spec.fast_window} > MA{spec.slow_window}，"
            f"RSI < {spec.rsi_overbought:g}"
        )
        exit_condition = f"收盘价跌破 MA{spec.fast_window}，或触发止损/止盈"
    else:
        entry_condition = f"收盘价跌破 {spec.fast_window} 日布林下轨，且 RSI < {spec.rsi_oversold:g}"
        exit_condition = f"收盘价回到 MA{spec.fast_window} 上方、RSI > 50，或触发止损/止盈"
    if spec.volume_filter:
        entry_condition += "，成交量不低于 20 日均量"

    buying = action == "conditional_buy"
    return TradeSignal(
        action=action,
        data_as_of=market.data_as_of,
        execution_window="下一交易日（基于日线信号）" if action in {"conditional_buy", "sell"} else "暂不执行交易",
        entry_condition=entry_condition,
        exit_condition=exit_condition,
        reference_price=round(latest_close, 2),
        stop_price=round(latest_close - spec.stop_loss_atr * latest_atr, 2) if buying else None,
        take_profit_price=round(latest_close * (1 + spec.take_profit_pct), 2) if buying else None,
        position_pct=risk.position_pct if buying else 0,
        rationale=f"{spec.rationale} 风控结论：{risk.summary}",
    )
