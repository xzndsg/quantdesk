from __future__ import annotations

from typing import Any

import backtrader as bt
import pandas as pd

from .models import BacktestResult, StrategySpec


class QuantStrategy(bt.Strategy):
    params = (("spec", None),)

    def __init__(self) -> None:
        spec: StrategySpec = self.p.spec
        self.ma_fast = bt.ind.SMA(self.data.close, period=spec.fast_window)
        self.ma_slow = bt.ind.SMA(self.data.close, period=spec.slow_window)
        self.rsi = bt.ind.RSI_Safe(self.data.close, period=spec.rsi_period)
        self.atr = bt.ind.ATR(self.data, period=spec.rsi_period)
        self.volume_ma = bt.ind.SMA(self.data.volume, period=20)
        self.bollinger = bt.ind.BollingerBands(
            self.data.close, period=spec.fast_window, devfactor=2.0
        )
        self.order = None
        self.entry_price: float | None = None
        self.entry_atr: float | None = None
        self.entry_size = 0
        self.trade_records: list[dict[str, Any]] = []

    def _entry_signal(self) -> bool:
        spec: StrategySpec = self.p.spec
        if spec.strategy_type == "trend":
            signal = (
                self.data.close[0] > self.ma_fast[0]
                and self.ma_fast[0] > self.ma_slow[0]
                and self.rsi[0] < spec.rsi_overbought
            )
        else:
            signal = self.data.close[0] < self.bollinger.bot[0] and self.rsi[0] < spec.rsi_oversold
        if spec.volume_filter:
            signal = signal and self.data.volume[0] >= self.volume_ma[0]
        return bool(signal)

    def _exit_signal(self) -> bool:
        spec: StrategySpec = self.p.spec
        if spec.strategy_type == "trend":
            technical_exit = self.data.close[0] < self.ma_fast[0]
        else:
            technical_exit = self.data.close[0] > self.ma_fast[0] or self.rsi[0] > 50
        if self.entry_price is None or self.entry_atr is None:
            return bool(technical_exit)
        stop_price = self.entry_price - spec.stop_loss_atr * self.entry_atr
        take_profit_price = self.entry_price * (1 + spec.take_profit_pct)
        return bool(
            technical_exit
            or self.data.close[0] <= stop_price
            or self.data.close[0] >= take_profit_price
        )

    def next(self) -> None:
        if self.order is not None:
            return
        if not self.position:
            if self._entry_signal():
                spec: StrategySpec = self.p.spec
                budget = self.broker.getvalue() * spec.max_position_pct
                size = int(budget / self.data.close[0] / 100) * 100
                if size >= 100:
                    self.order = self.buy(size=size)
        elif self._exit_signal():
            self.order = self.close()

    def notify_order(self, order: bt.Order) -> None:
        if order.status == order.Completed and order.isbuy():
            self.entry_price = float(order.executed.price)
            self.entry_atr = float(self.atr[0])
            self.entry_size = abs(int(order.executed.size))
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None

    def notify_trade(self, trade: bt.Trade) -> None:
        if not trade.isclosed:
            return
        cost = (self.entry_price or trade.price) * self.entry_size
        self.trade_records.append(
            {
                "买入日期": bt.num2date(trade.dtopen).date().isoformat(),
                "卖出日期": bt.num2date(trade.dtclose).date().isoformat(),
                "数量": self.entry_size,
                "买入价": round(self.entry_price or trade.price, 4),
                "卖出价": round(float(trade.price + trade.pnl / self.entry_size), 4)
                if self.entry_size
                else None,
                "净盈亏": round(float(trade.pnlcomm), 2),
                "收益率%": round(float(trade.pnlcomm / cost * 100), 2) if cost else 0,
            }
        )
        self.entry_price = None
        self.entry_atr = None
        self.entry_size = 0


def run_backtest(
    history: pd.DataFrame,
    spec: StrategySpec,
    initial_cash: float,
    commission: float = 0.0003,
    slippage: float = 0.001,
) -> BacktestResult:
    if len(history) < spec.slow_window + 30:
        raise ValueError(f"回测区间至少需要 {spec.slow_window + 30} 条行情")

    frame = history[["open", "high", "low", "close", "volume"]].copy()
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(QuantStrategy, spec=spec)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)
    cerebro.broker.set_slippage_perc(slippage, slip_open=True, slip_match=True)
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio,
        _name="sharpe",
        timeframe=bt.TimeFrame.Days,
        annualize=True,
        riskfreerate=0.02,
    )
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    strategy = cerebro.run()[0]
    final_value = float(cerebro.broker.getvalue())
    total_return = (final_value / initial_cash - 1) * 100
    days = max(1, (frame.index[-1] - frame.index[0]).days)
    annual_return = ((final_value / initial_cash) ** (365 / days) - 1) * 100
    sharpe = strategy.analyzers.sharpe.get_analysis().get("sharperatio") or 0
    max_drawdown = float(strategy.analyzers.drawdown.get_analysis()["max"]["drawdown"])
    trade_analysis = strategy.analyzers.trades.get_analysis()
    trade_count = int(trade_analysis.get("total", {}).get("closed", 0))
    won = int(trade_analysis.get("won", {}).get("total", 0))
    win_rate = won / trade_count * 100 if trade_count else 0
    score = float(sharpe) + total_return / 100 - max_drawdown / 100

    return BacktestResult(
        start_date=frame.index[0].date().isoformat(),
        end_date=frame.index[-1].date().isoformat(),
        initial_cash=round(initial_cash, 2),
        final_value=round(final_value, 2),
        total_return_pct=round(total_return, 2),
        annual_return_pct=round(annual_return, 2),
        sharpe=round(float(sharpe), 4),
        max_drawdown_pct=round(max_drawdown, 2),
        trade_count=trade_count,
        win_rate_pct=round(win_rate, 2),
        score=round(score, 4),
        trades=strategy.trade_records,
    )
