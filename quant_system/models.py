from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    deepseek_api_key: SecretStr = Field(repr=False)
    max_iterations: int = Field(default=3, ge=1, le=5)
    initial_cash: float = Field(default=100_000, gt=0)
    lookback_years: int = Field(default=3, ge=2, le=5)
    risk_level: Literal["保守", "稳健", "积极"] = "稳健"

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        value = value.strip()
        if len(value) != 6 or not value.isdigit():
            raise ValueError("股票代码必须是 6 位数字")
        return value

    @field_validator("deepseek_api_key")
    @classmethod
    def validate_key(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().strip()) < 5:
            raise ValueError("DeepSeek API Key 不能为空")
        return value


@dataclass
class MarketBundle:
    symbol: str
    data_as_of: str
    source: str
    history: pd.DataFrame
    summary: dict[str, Any]


class NewsItem(BaseModel):
    title: str
    content: str = Field(default="", repr=False)
    published_at: str = ""
    source: str = ""
    url: str = ""
    event_type: str = "未分析"
    sentiment: Literal["正面", "中性", "负面"] = "中性"
    impact: str = "未分析"
    confidence: float = Field(default=0, ge=0, le=1)
    reason: str = ""


class NewsContext(BaseModel):
    items: list[NewsItem] = Field(default_factory=list)
    overall_sentiment: Literal["正面", "中性", "负面"] = "中性"
    score: float = Field(default=0, ge=-1, le=1)
    summary: str = "暂无可用新闻"


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    strategy_type: Literal["trend", "mean_reversion"]
    fast_window: int = Field(ge=5, le=60)
    slow_window: int = Field(ge=20, le=120)
    rsi_period: int = Field(default=14, ge=5, le=30)
    rsi_overbought: float = Field(default=70, ge=55, le=90)
    rsi_oversold: float = Field(default=30, ge=10, le=45)
    volume_filter: bool = True
    stop_loss_atr: float = Field(default=2, ge=1, le=5)
    take_profit_pct: float = Field(default=0.15, ge=0.03, le=0.5)
    max_position_pct: float = Field(default=0.2, ge=0.05, le=0.3)
    rationale: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_windows(self) -> "StrategySpec":
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window 必须小于 slow_window")
        if self.rsi_oversold >= self.rsi_overbought:
            raise ValueError("RSI 超卖阈值必须小于超买阈值")
        return self


class BacktestResult(BaseModel):
    start_date: str
    end_date: str
    initial_cash: float
    final_value: float
    total_return_pct: float
    annual_return_pct: float
    sharpe: float
    max_drawdown_pct: float
    trade_count: int
    win_rate_pct: float
    score: float
    trades: list[dict[str, Any]] = Field(default_factory=list)


class IterationRecord(BaseModel):
    iteration: int
    strategy: StrategySpec
    train: BacktestResult
    validation: BacktestResult
    passed: bool
    feedback: str


class RiskCheck(BaseModel):
    name: str
    status: Literal["PASS", "WARN", "BLOCK"]
    detail: str


class RiskReport(BaseModel):
    status: Literal["PASS", "REDUCE", "WATCH", "BLOCK"]
    position_pct: float = Field(ge=0, le=1)
    checks: list[RiskCheck]
    summary: str


class TradeSignal(BaseModel):
    action: Literal["conditional_buy", "sell", "watch", "blocked"]
    data_as_of: str
    execution_window: str
    entry_condition: str
    exit_condition: str
    reference_price: float | None = None
    stop_price: float | None = None
    take_profit_price: float | None = None
    position_pct: float = Field(default=0, ge=0, le=1)
    rationale: str


class LogEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    run_id: str
    stage: str
    level: Literal["INFO", "WARNING", "ERROR"] = "INFO"
    message: str
    iteration: int | None = None
    duration_ms: int | None = None


class AnalysisReport(BaseModel):
    run_id: str
    symbol: str
    created_at: str
    data_as_of: str
    market_summary: dict[str, Any]
    news: NewsContext
    iterations: list[IterationRecord]
    best_strategy: StrategySpec
    final_backtest: BacktestResult
    risk: RiskReport
    signal: TradeSignal
    logs: list[LogEvent]
