from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import akshare as ak
import numpy as np
import pandas as pd

from .models import MarketBundle, NewsItem


def _round(value: Any, digits: int = 4) -> float | None:
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        return None
    return round(float(value), digits)


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return rsi.where(avg_loss != 0, 100)


def calculate_atr(history: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = history["close"].shift(1)
    true_range = pd.concat(
        [
            history["high"] - history["low"],
            (history["high"] - previous_close).abs(),
            (history["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def add_common_indicators(history: pd.DataFrame) -> pd.DataFrame:
    result = history.copy()
    result["ma20"] = result["close"].rolling(20).mean()
    result["ma60"] = result["close"].rolling(60).mean()
    result["rsi14"] = calculate_rsi(result["close"], 14)
    result["atr14"] = calculate_atr(result, 14)
    result["volume_ma20"] = result["volume"].rolling(20).mean()
    return result


def _benchmark_return(start_date: str, end_date: str) -> float | None:
    try:
        benchmark = ak.index_zh_daily_sina(symbol="sh000300")
        dates = pd.to_datetime(benchmark["date"], errors="coerce")
        in_range = dates.between(pd.to_datetime(start_date), pd.to_datetime(end_date))
        closes = pd.to_numeric(
            benchmark.loc[in_range, "close"], errors="coerce"
        ).dropna()
        if len(closes) < 2:
            return None
        window = closes.tail(61)
        return _round((window.iloc[-1] / window.iloc[0] - 1) * 100, 2)
    except Exception:
        return None


def fetch_market(symbol: str, years: int, logger: Any) -> MarketBundle:
    end = datetime.now().date()
    start = end - timedelta(days=365 * years + 30)
    start_date = start.strftime("%Y%m%d")
    end_date = end.strftime("%Y%m%d")
    logger.info("MARKET", f"开始获取 {symbol} 日线行情")

    source = "akshare/新浪财经"
    exchange_symbol = f"{'sh' if symbol.startswith('6') else 'sz'}{symbol}"
    try:
        raw = ak.stock_zh_a_hist_sina(
            symbol=exchange_symbol,
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        if raw is None or raw.empty:
            raise ValueError("新浪未返回有效行情")
    except Exception as exc:
        logger.warning(
            "MARKET",
            f"新浪行情不可用（{type(exc).__name__}），切换腾讯备用行情",
        )
        try:
            raw = ak.stock_zh_a_hist_tx(
                symbol=exchange_symbol,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
        except Exception as fallback_exc:
            raise ValueError("新浪和腾讯行情均不可用，请稍后重试") from fallback_exc
        source = "akshare/腾讯证券"
        logger.info("MARKET", f"腾讯备用行情返回 {0 if raw is None else len(raw)} 条")
    if raw is None or raw.empty:
        raise ValueError("未获取到行情，请检查股票代码或稍后重试")

    columns = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
    }
    history = raw.rename(columns=columns)[list(columns.values())].copy()
    history["date"] = pd.to_datetime(history["date"], errors="coerce")
    for column in ["open", "close", "high", "low", "volume", "amount"]:
        history[column] = pd.to_numeric(history[column], errors="coerce")
    history = history.dropna().sort_values("date").drop_duplicates("date").set_index("date")
    if len(history) < 120:
        raise ValueError("有效行情不足 120 条，无法进行可靠回测")
    history = add_common_indicators(history)

    close = history["close"]
    return_20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) > 20 else None
    return_60 = (close.iloc[-1] / close.iloc[-61] - 1) * 100 if len(close) > 60 else None
    volatility = close.pct_change().tail(60).std() * np.sqrt(252) * 100
    benchmark_return = _benchmark_return(start_date, end_date)
    latest = history.iloc[-1]
    summary = {
        "data_source": source,
        "rows": len(history),
        "latest_close": _round(latest["close"], 2),
        "return_20d_pct": _round(return_20, 2),
        "return_60d_pct": _round(return_60, 2),
        "annual_volatility_60d_pct": _round(volatility, 2),
        "ma20": _round(latest["ma20"], 2),
        "ma60": _round(latest["ma60"], 2),
        "rsi14": _round(latest["rsi14"], 2),
        "atr14": _round(latest["atr14"], 4),
        "avg_amount_20d": _round(history["amount"].tail(20).mean(), 0),
        "benchmark_return_60d_pct": benchmark_return,
        "relative_strength_60d_pct": (
            _round(return_60 - benchmark_return, 2)
            if return_60 is not None and benchmark_return is not None
            else None
        ),
    }
    data_as_of = history.index[-1].date().isoformat()
    logger.info(
        "MARKET",
        f"行情完成：{len(history)} 条，数据截至 {data_as_of}，来源 {source}",
    )
    return MarketBundle(symbol, data_as_of, source, history, summary)


def fetch_news(symbol: str, logger: Any, limit: int = 20) -> list[NewsItem]:
    logger.info("NEWS", "开始获取公开新闻")
    try:
        raw = ak.stock_news_em(symbol=symbol)
        if raw is None or raw.empty:
            logger.warning("NEWS", "未获取到相关新闻，后续按证据不足处理")
            return []
        records = raw.head(limit)
        items = [
            NewsItem(
                title=str(row.get("新闻标题", "")).strip(),
                content=str(row.get("新闻内容", "")).strip(),
                published_at=str(row.get("发布时间", "")),
                source=str(row.get("文章来源", "")),
                url=str(row.get("新闻链接", "")),
            )
            for _, row in records.iterrows()
            if str(row.get("新闻标题", "")).strip()
        ]
        logger.info("NEWS", f"获取到 {len(items)} 条新闻")
        return items
    except Exception as exc:
        logger.warning("NEWS", f"新闻源不可用，按证据不足继续：{type(exc).__name__}")
        return []
