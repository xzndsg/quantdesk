from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import pandas as pd

from .ai import DeepSeekService
from .backtest import run_backtest
from .market import fetch_market, fetch_news
from .models import (
    AnalysisReport,
    AnalysisRequest,
    IterationRecord,
    LogEvent,
)
from .risk import evaluate_risk, generate_signal


class RunLogger:
    def __init__(self, run_id: str, callback: Callable[[LogEvent], None] | None = None) -> None:
        self.run_id = run_id
        self.callback = callback
        self.events: list[LogEvent] = []

    def log(
        self,
        level: str,
        stage: str,
        message: str,
        iteration: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        event = LogEvent(
            run_id=self.run_id,
            stage=stage,
            level=level,
            message=message,
            iteration=iteration,
            duration_ms=duration_ms,
        )
        self.events.append(event)
        if self.callback:
            self.callback(event)

    def info(self, stage: str, message: str, **kwargs) -> None:
        self.log("INFO", stage, message, **kwargs)

    def warning(self, stage: str, message: str, **kwargs) -> None:
        self.log("WARNING", stage, message, **kwargs)

    def error(self, stage: str, message: str, **kwargs) -> None:
        self.log("ERROR", stage, message, **kwargs)


@dataclass
class EngineResult:
    report: AnalysisReport
    history: pd.DataFrame


class QuantEngine:
    def __init__(
        self,
        request: AnalysisRequest,
        callback: Callable[[LogEvent], None] | None = None,
    ) -> None:
        self.request = request
        self.run_id = f"run_{uuid.uuid4().hex[:12]}"
        self.logger = RunLogger(self.run_id, callback)

    def run(self) -> EngineResult:
        started = time.perf_counter()
        try:
            self.logger.info(
                "INPUT",
                f"任务创建：{self.request.symbol}，迭代上限 {self.request.max_iterations} 次",
            )
            ai = DeepSeekService(
                self.request.deepseek_api_key.get_secret_value(), self.logger
            )
            market = fetch_market(self.request.symbol, self.request.lookback_years, self.logger)
            news = ai.analyze_news(fetch_news(self.request.symbol, self.logger))

            history = market.history
            train_end = int(len(history) * 0.6)
            validation_end = int(len(history) * 0.8)
            train_data = history.iloc[:train_end]
            validation_data = history.iloc[train_end:validation_end]
            holdout_data = history.iloc[validation_end:]
            self.logger.info(
                "BACKTEST",
                f"数据按时间划分：训练 {len(train_data)} / 验证 {len(validation_data)} / 留出 {len(holdout_data)}",
            )

            records: list[IterationRecord] = []
            previous_feedback: list[dict] = []
            best_record: IterationRecord | None = None
            stale_rounds = 0
            iteration_limit = min(self.request.max_iterations, 5)

            for iteration in range(1, iteration_limit + 1):
                iteration_started = time.perf_counter()
                strategy = ai.generate_strategy(
                    market.summary, news, previous_feedback, iteration
                )
                try:
                    train_result = run_backtest(
                        train_data, strategy, self.request.initial_cash
                    )
                    validation_result = run_backtest(
                        validation_data, strategy, self.request.initial_cash
                    )
                except ValueError as exc:
                    self.logger.warning(
                        "BACKTEST", f"本轮回测跳过：{exc}", iteration=iteration
                    )
                    previous_feedback.append(
                        {
                            "iteration": iteration,
                            "strategy": strategy.model_dump(),
                            "error": str(exc),
                        }
                    )
                    continue

                passed = (
                    validation_result.trade_count >= 1
                    and validation_result.total_return_pct > 0
                    and validation_result.sharpe > 0
                    and validation_result.max_drawdown_pct <= 30
                )
                feedback = (
                    f"验证收益 {validation_result.total_return_pct:.2f}%，"
                    f"夏普 {validation_result.sharpe:.2f}，"
                    f"回撤 {validation_result.max_drawdown_pct:.2f}%"
                )
                record = IterationRecord(
                    iteration=iteration,
                    strategy=strategy,
                    train=train_result,
                    validation=validation_result,
                    passed=passed,
                    feedback=feedback,
                )
                records.append(record)
                self.logger.info(
                    "BACKTEST",
                    feedback + f"，{'通过' if passed else '未通过'}",
                    iteration=iteration,
                    duration_ms=int((time.perf_counter() - iteration_started) * 1000),
                )
                previous_feedback.append(
                    {
                        "iteration": iteration,
                        "strategy": strategy.model_dump(),
                        "validation": validation_result.model_dump(exclude={"trades"}),
                        "passed": passed,
                    }
                )

                if best_record is None or validation_result.score > best_record.validation.score:
                    best_record = record
                    stale_rounds = 0
                else:
                    stale_rounds += 1

                if (
                    passed
                    and validation_result.sharpe >= 0.5
                    and validation_result.max_drawdown_pct <= 20
                ):
                    self.logger.info("BACKTEST", "验证指标达到提前停止条件", iteration=iteration)
                    break
                if stale_rounds >= 2:
                    self.logger.info("BACKTEST", "连续两轮无改善，提前停止", iteration=iteration)
                    break

            if best_record is None:
                raise RuntimeError("没有候选策略完成回测，请减少均线窗口或扩大回测周期")

            self.logger.info("BACKTEST", "使用最佳验证策略执行最终留出集回测")
            final_result = run_backtest(
                holdout_data, best_record.strategy, self.request.initial_cash
            )
            risk = evaluate_risk(
                market,
                news,
                final_result,
                best_record.strategy,
                self.request.risk_level,
            )
            signal = generate_signal(market, best_record.strategy, risk)
            self.logger.info("RISK", f"风控状态 {risk.status}，最终动作 {signal.action}")
            self.logger.info(
                "DONE",
                "分析完成",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            report = AnalysisReport(
                run_id=self.run_id,
                symbol=self.request.symbol,
                created_at=datetime.now().astimezone().isoformat(),
                data_as_of=market.data_as_of,
                market_summary=market.summary,
                news=news,
                iterations=records,
                best_strategy=best_record.strategy,
                final_backtest=final_result,
                risk=risk,
                signal=signal,
                logs=list(self.logger.events),
            )
            return EngineResult(report=report, history=history)
        except Exception as exc:
            self.logger.error("ERROR", f"任务终止：{exc}")
            raise
