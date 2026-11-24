from __future__ import annotations

import json
from html import escape

import streamlit as st
from pydantic import ValidationError

from quant_system.credentials import load_api_key, save_api_key
from quant_system.engine import EngineResult, QuantEngine
from quant_system.models import AnalysisRequest, LogEvent


st.set_page_config(page_title="QuantDesk · A 股 AI 量化研究", layout="wide")

ACTION_META = {
    "conditional_buy": ("条件买入", "buy", "技术条件已满足，仍需人工确认后执行"),
    "sell": ("卖出 / 退出", "sell", "策略已触发退出条件，优先控制风险"),
    "watch": ("继续观望", "watch", "当前没有满足条件的交易机会"),
    "blocked": ("风控阻断", "blocked", "存在硬性风险项，不输出买入建议"),
}
RISK_META = {
    "PASS": ("风险检查通过", "pass"),
    "REDUCE": ("建议降低仓位", "reduce"),
    "WATCH": ("风险观察", "watch"),
    "BLOCK": ("风险阻断", "blocked"),
}
PIPELINE_STAGES = [
    ("MARKET", "市场行情"),
    ("NEWS", "新闻分析"),
    ("STRATEGY", "策略生成"),
    ("BACKTEST", "迭代回测"),
    ("RISK", "风险控制"),
    ("DONE", "研究完成"),
]


def inject_styles() -> None:
    st.markdown(
        """
<style>
:root {
    --page-bg: #f4f6fa;
    --surface: #ffffff;
    --surface-soft: #f8fafc;
    --text: #172033;
    --text-secondary: #667085;
    --text-tertiary: #98a2b3;
    --border: #e4e9f0;
    --primary: #315efb;
    --primary-hover: #2448d8;
    --primary-soft: #edf2ff;
    --success: #087f5b;
    --success-soft: #e9f7f1;
    --warning: #a15c00;
    --warning-soft: #fff5e6;
    --danger: #c92a2a;
    --danger-soft: #fff0f0;
    --shadow: 0 1px 2px rgba(16, 24, 40, 0.04), 0 4px 16px rgba(16, 24, 40, 0.03);
}
html, body, [class*="css"] {
    font-family: Inter, "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif;
}
.stApp, [data-testid="stAppViewContainer"] {
    background: var(--page-bg);
    color: var(--text);
}
[data-testid="stHeader"] {
    background: transparent;
}
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
.block-container {
    max-width: 1480px;
    padding: 1.8rem 2.4rem 2rem;
}
[data-testid="stForm"] {
    border: 0;
    padding: 0;
}
[data-testid="stWidgetLabel"] p {
    color: #475467;
    font-size: 0.78rem;
    font-weight: 600;
}
[data-testid="stVerticalBlockBorderWrapper"]:has([data-testid="stForm"]) {
    background: var(--surface);
    border-color: var(--border);
    border-radius: 14px;
    box-shadow: var(--shadow);
    margin-bottom: 1.2rem;
    padding: 1.1rem 1.25rem 0.9rem;
}
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background: var(--surface);
    border: 1px solid #dce3ec;
    border-radius: 8px;
    color: var(--text);
    min-height: 40px;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(49, 94, 251, 0.10);
}
[data-baseweb="select"] > div {
    background: var(--surface);
    border-color: #dce3ec;
    border-radius: 8px;
}
[data-testid="stForm"] [data-testid="stExpander"] {
    background: var(--surface-soft);
    box-shadow: none;
}
[data-testid="stFormSubmitButton"] button,
.stButton button[kind="primary"],
button[data-testid="stBaseButton-primary"] {
    background: var(--primary);
    border: 1px solid var(--primary);
    border-radius: 8px;
    box-shadow: 0 2px 5px rgba(49, 94, 251, 0.18);
    color: #ffffff;
    font-weight: 600;
    min-height: 42px;
}
[data-testid="stFormSubmitButton"] button:hover,
.stButton button[kind="primary"]:hover,
button[data-testid="stBaseButton-primary"]:hover {
    background: var(--primary-hover);
    border-color: var(--primary-hover);
    color: #ffffff;
}
[data-testid="stDownloadButton"] button {
    background: var(--surface);
    border: 1px solid #d8e0ea;
    border-radius: 8px;
    color: #344054;
    font-weight: 600;
}
[data-testid="stDownloadButton"] button:hover {
    border-color: var(--primary);
    color: var(--primary);
}
[data-testid="stMetric"] {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    box-shadow: var(--shadow);
    min-height: 108px;
    padding: 17px 18px;
}
[data-testid="stMetricLabel"] {
    color: var(--text-secondary);
    font-size: 0.78rem;
    font-weight: 500;
}
[data-testid="stMetricValue"] {
    color: var(--text);
    font-size: 1.55rem;
    font-weight: 650;
    letter-spacing: -0.02em;
}
[data-testid="stHorizontalBlock"] { gap: 0.9rem; }
[data-baseweb="tab-list"] {
    background: #e9edf4;
    border: 1px solid #e1e6ee;
    border-radius: 10px;
    gap: 4px;
    margin: 0 0 1.4rem;
    padding: 4px;
}
[data-baseweb="tab"] {
    background: transparent;
    border-radius: 7px;
    color: var(--text-secondary);
    font-size: 0.88rem;
    font-weight: 550;
    height: 40px;
    padding: 0 20px;
}
[data-baseweb="tab"][aria-selected="true"] {
    background: var(--surface);
    box-shadow: 0 1px 4px rgba(16, 24, 40, 0.10);
    color: var(--primary);
}
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display: none; }
[data-testid="stDataFrame"] {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
}
[data-testid="stExpander"] {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px !important;
    overflow: hidden;
}
[data-testid="stAlert"] {
    border-radius: 10px;
    box-shadow: none;
}
[data-testid="stCode"] {
    border: 1px solid var(--border);
    border-radius: 10px;
}
[data-testid="stProgressBar"] > div > div { background-color: var(--primary); }
.app-header {
    align-items: center;
    display: flex;
    justify-content: space-between;
    margin-bottom: 1.7rem;
    padding: 0.15rem 0 0.2rem;
}
.app-eyebrow {
    color: var(--primary);
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    margin-bottom: 0.45rem;
}
.app-title {
    color: var(--text);
    font-size: 1.85rem;
    font-weight: 700;
    letter-spacing: -0.035em;
    line-height: 1.25;
}
.app-subtitle {
    color: var(--text-secondary);
    font-size: 0.88rem;
    margin-top: 0.5rem;
}
.mode-badge {
    align-items: center;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 999px;
    color: #475467;
    display: flex;
    font-size: 0.76rem;
    font-weight: 550;
    gap: 7px;
    padding: 8px 13px;
    white-space: nowrap;
}
.mode-dot { background: var(--success); border-radius: 50%; height: 7px; width: 7px; }
.config-topline {
    align-items: center;
    display: flex;
    justify-content: space-between;
    margin-bottom: 0.85rem;
}
.config-eyebrow { color: var(--primary); font-size: 0.62rem; font-weight: 700; letter-spacing: 0.12em; }
.config-title { color: var(--text); font-size: 1.05rem; font-weight: 680; margin-top: 3px; }
.config-source {
    background: var(--surface-soft);
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--text-secondary);
    font-size: 0.68rem;
    padding: 6px 11px;
}
.config-note { color: var(--text-tertiary); font-size: 0.68rem; margin-top: 0.65rem; }
[data-testid="stFormSubmitButton"] button { font-size: 0.9rem; min-height: 44px; }
.welcome-panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    box-shadow: var(--shadow);
    padding: 28px 30px 26px;
}
.welcome-kicker { color: var(--primary); font-size: 0.72rem; font-weight: 650; letter-spacing: 0.06em; }
.welcome-title { color: var(--text); font-size: 1.45rem; font-weight: 650; letter-spacing: -0.025em; margin-top: 8px; }
.welcome-copy { color: var(--text-secondary); font-size: 0.88rem; line-height: 1.75; margin-top: 10px; max-width: 780px; }
.workflow-grid { display: grid; gap: 12px; grid-template-columns: repeat(4, 1fr); margin-top: 24px; }
.workflow-item { background: var(--surface-soft); border: 1px solid var(--border); border-radius: 11px; padding: 17px; }
.workflow-number { color: var(--primary); font-family: monospace; font-size: 0.72rem; font-weight: 700; }
.workflow-title { color: var(--text); font-size: 0.92rem; font-weight: 650; margin-top: 10px; }
.workflow-copy { color: var(--text-secondary); font-size: 0.75rem; line-height: 1.6; margin-top: 6px; }
.welcome-note { color: var(--text-tertiary); font-size: 0.72rem; margin-top: 20px; }
.result-heading { align-items: flex-end; display: flex; justify-content: space-between; margin-bottom: 1.15rem; }
.result-kicker { color: var(--text-tertiary); font-size: 0.68rem; font-weight: 650; letter-spacing: 0.1em; }
.result-title { color: var(--text); font-size: 1.5rem; font-weight: 680; letter-spacing: -0.025em; margin-top: 4px; }
.run-meta { color: var(--text-tertiary); font-family: monospace; font-size: 0.7rem; }
.section-header { margin: 1.4rem 0 0.85rem; }
.section-title { color: var(--text); font-size: 1rem; font-weight: 650; }
.section-subtitle { color: var(--text-secondary); font-size: 0.76rem; margin-top: 4px; }
.signal-card {
    --tone: var(--primary);
    --tone-soft: var(--primary-soft);
    align-items: center;
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 4px solid var(--tone);
    border-radius: 13px;
    box-shadow: var(--shadow);
    display: flex;
    justify-content: space-between;
    margin-bottom: 1rem;
    padding: 22px 24px;
}
.signal-card.tone-sell, .signal-card.tone-reduce { --tone: var(--warning); --tone-soft: var(--warning-soft); }
.signal-card.tone-blocked { --tone: var(--danger); --tone-soft: var(--danger-soft); }
.signal-card.tone-watch { --tone: #667085; --tone-soft: #f0f2f5; }
.signal-card.tone-pass { --tone: var(--success); --tone-soft: var(--success-soft); }
.signal-kicker { color: var(--text-tertiary); font-size: 0.65rem; font-weight: 650; letter-spacing: 0.1em; }
.signal-main { align-items: center; color: var(--tone); display: flex; font-size: 1.65rem; font-weight: 680; gap: 12px; margin-top: 5px; }
.signal-description { color: var(--text-secondary); font-size: 0.8rem; margin-top: 7px; }
.signal-asof { text-align: right; }
.signal-asof span { color: var(--text-tertiary); display: block; font-size: 0.68rem; }
.signal-asof strong { color: var(--text); display: block; font-size: 0.88rem; margin-top: 5px; }
.status-pill { background: var(--tone-soft); border-radius: 999px; color: var(--tone); font-size: 0.65rem; font-weight: 650; padding: 5px 9px; }
.detail-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 11px; height: 100%; padding: 17px 18px; }
.detail-title { color: var(--text); font-size: 0.82rem; font-weight: 650; }
.detail-copy { color: var(--text-secondary); font-size: 0.8rem; line-height: 1.75; margin-top: 8px; white-space: pre-wrap; }
.pipeline { background: var(--surface); border: 1px solid var(--border); border-radius: 11px; display: grid; gap: 8px; grid-template-columns: repeat(6, 1fr); margin-bottom: 14px; padding: 13px 15px; }
.pipeline-item { align-items: center; color: var(--text-tertiary); display: flex; font-size: 0.72rem; gap: 7px; justify-content: center; }
.pipeline-number { align-items: center; background: #edf0f4; border-radius: 50%; display: flex; font-family: monospace; font-size: 0.65rem; height: 22px; justify-content: center; width: 22px; }
.pipeline-item.active { color: var(--primary); font-weight: 650; }
.pipeline-item.active .pipeline-number { background: var(--primary); color: #fff; }
.pipeline-item.done { color: var(--success); }
.pipeline-item.done .pipeline-number { background: var(--success-soft); color: var(--success); }
.app-footer { border-top: 1px solid var(--border); color: var(--text-tertiary); font-size: 0.7rem; line-height: 1.75; margin-top: 2rem; padding-top: 1rem; }
.app-footer strong { color: var(--text-secondary); font-weight: 600; }
@media (max-width: 1000px) {
    .block-container { padding: 1.4rem 1.3rem 1.6rem; }
    .app-header { align-items: flex-start; gap: 14px; }
    .app-title { font-size: 1.5rem; }
    .mode-badge { font-size: 0; padding: 8px; }
    .workflow-grid { grid-template-columns: repeat(2, 1fr); }
    .pipeline { grid-template-columns: repeat(3, 1fr); row-gap: 12px; }
}
@media (max-width: 640px) {
    .config-topline { align-items: flex-start; gap: 12px; }
    .config-source { font-size: 0.6rem; }
    .workflow-grid { grid-template-columns: 1fr; }
    .welcome-panel { padding: 22px; }
    .signal-card { align-items: flex-start; gap: 16px; }
    .signal-main { font-size: 1.35rem; }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def format_log(event: LogEvent) -> str:
    iteration = f" 第{event.iteration}轮" if event.iteration else ""
    duration = f" {event.duration_ms}ms" if event.duration_ms is not None else ""
    return (
        f"{event.timestamp:%H:%M:%S} [{event.level}] {event.stage}{iteration} "
        f"{event.message}{duration}"
    )


def section_header(title: str, subtitle: str = "") -> None:
    subtitle_html = (
        f'<div class="section-subtitle">{escape(subtitle)}</div>' if subtitle else ""
    )
    st.markdown(
        f'<div class="section-header"><div class="section-title">{escape(title)}</div>'
        f"{subtitle_html}</div>",
        unsafe_allow_html=True,
    )


def text_panel(title: str, text: str) -> None:
    st.markdown(
        f'<div class="detail-panel"><div class="detail-title">{escape(title)}</div>'
        f'<div class="detail-copy">{escape(text or "暂无")}</div></div>',
        unsafe_allow_html=True,
    )


def status_banner(
    kicker: str,
    title: str,
    description: str,
    tone: str,
    aside_label: str,
    aside_value: str,
    pill: str,
) -> None:
    st.markdown(
        f"""
<div class="signal-card tone-{escape(tone)}">
    <div>
        <div class="signal-kicker">{escape(kicker)}</div>
        <div class="signal-main">{escape(title)}<span class="status-pill">{escape(pill)}</span></div>
        <div class="signal-description">{escape(description)}</div>
    </div>
    <div class="signal-asof"><span>{escape(aside_label)}</span><strong>{escape(aside_value)}</strong></div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_pipeline(active_stage: str, completed: bool = False) -> None:
    stage_keys = [key for key, _ in PIPELINE_STAGES]
    active_index = stage_keys.index(active_stage) if active_stage in stage_keys else 0
    items = []
    for index, (key, label) in enumerate(PIPELINE_STAGES):
        state = "done" if completed or index < active_index else ("active" if index == active_index else "")
        items.append(
            f'<div class="pipeline-item {state}"><span class="pipeline-number">{index + 1}</span>'
            f"<span>{label}</span></div>"
        )
    st.markdown(f'<div class="pipeline">{"".join(items)}</div>', unsafe_allow_html=True)


def render_header() -> None:
    st.markdown(
        """
<div class="app-header">
    <div>
        <div class="app-eyebrow">QUANTDESK / AI RESEARCH WORKBENCH</div>
        <div class="app-title">A 股 AI 量化研究系统</div>
        <div class="app-subtitle">将市场数据、新闻证据与策略回测整合为可审计的研究结论</div>
    </div>
    <div class="mode-badge"><span class="mode-dot"></span>研究模式 · 不自动交易</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_welcome() -> None:
    st.markdown(
        """
<div class="welcome-panel">
    <div class="welcome-kicker">从一只股票开始</div>
    <div class="welcome-title">建立有数据、有证据、有风控的研究流程</div>
    <div class="welcome-copy">在上方配置股票代码与 DeepSeek API Key。系统将按时间顺序完成数据分析、候选策略迭代和留出集验证，并清晰区分历史回测结果与当前条件信号。</div>
    <div class="workflow-grid">
        <div class="workflow-item"><div class="workflow-number">01</div><div class="workflow-title">市场洞察</div><div class="workflow-copy">前复权日线、趋势、波动率、流动性与相对强弱。</div></div>
        <div class="workflow-item"><div class="workflow-number">02</div><div class="workflow-title">新闻证据</div><div class="workflow-copy">事件分类、情绪评分、影响周期与判断依据。</div></div>
        <div class="workflow-item"><div class="workflow-number">03</div><div class="workflow-title">策略验证</div><div class="workflow-copy">有限迭代选优，训练、验证与留出集严格分离。</div></div>
        <div class="workflow-item"><div class="workflow-number">04</div><div class="workflow-title">独立风控</div><div class="workflow-copy">仓位约束、回撤检查与明确的风险阻断状态。</div></div>
    </div>
    <div class="welcome-note">全部结果支持 JSON 导出；API Key 不进入日志和研究报告。</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def show_result(result: EngineResult) -> None:
    report = result.report
    report_json = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
    heading, download = st.columns([5.5, 1.2], vertical_alignment="center")
    with heading:
        st.markdown(
            f'<div class="result-heading"><div><div class="result-kicker">RESEARCH REPORT</div>'
            f'<div class="result-title">{escape(report.symbol)} · 量化研究报告</div></div>'
            f'<div class="run-meta">{escape(report.run_id)}</div></div>',
            unsafe_allow_html=True,
        )
    with download:
        st.download_button(
            "导出研究报告",
            data=report_json.encode("utf-8"),
            file_name=f"{report.symbol}_{report.run_id}_report.json",
            mime="application/json",
            width="stretch",
        )

    signal_tab, market_tab, news_tab, strategy_tab, risk_tab, log_tab = st.tabs(
        ["交易信号", "市场调研", "新闻分析", "策略回测", "风险控制", "运行日志"]
    )

    with signal_tab:
        signal = report.signal
        action_label, tone, description = ACTION_META[signal.action]
        status_banner(
            "CURRENT TRADE SIGNAL",
            action_label,
            description,
            tone,
            "数据截至",
            signal.data_as_of,
            RISK_META[report.risk.status][0],
        )
        if signal.action == "blocked":
            st.error(report.risk.summary)
        elif signal.action in {"sell", "watch"}:
            st.warning(report.risk.summary)
        else:
            st.info(report.risk.summary)

        section_header("信号参数", "所有价格均基于最近一个已收盘交易日")
        columns = st.columns(4)
        columns[0].metric("数据截至", signal.data_as_of)
        columns[1].metric("参考收盘价", f"¥{signal.reference_price:.2f}")
        columns[2].metric("执行窗口", signal.execution_window)
        columns[3].metric("仓位上限", f"{signal.position_pct:.1%}")
        if signal.stop_price is not None:
            columns = st.columns(2)
            columns[0].metric("ATR 止损参考", f"¥{signal.stop_price:.2f}")
            columns[1].metric("止盈参考", f"¥{signal.take_profit_price:.2f}")

        section_header("交易条件", "条件触发不等于自动下单，执行前仍需人工复核")
        condition_columns = st.columns(2)
        with condition_columns[0]:
            text_panel("买入触发条件", signal.entry_condition)
        with condition_columns[1]:
            text_panel("退出触发条件", signal.exit_condition)
        section_header("信号依据")
        text_panel("策略与风控联合结论", signal.rationale)

    with market_tab:
        summary = report.market_summary
        latest_close = summary.get("latest_close")
        return_20d = summary.get("return_20d_pct")
        return_60d = summary.get("return_60d_pct")
        volatility = summary.get("annual_volatility_60d_pct")
        section_header("市场概览", "趋势、收益与波动指标")
        columns = st.columns(4)
        columns[0].metric("最新收盘价", f"¥{latest_close:.2f}" if latest_close is not None else "暂无")
        columns[1].metric("20 日涨跌幅", f"{return_20d:.2f}%" if return_20d is not None else "暂无")
        columns[2].metric("60 日涨跌幅", f"{return_60d:.2f}%" if return_60d is not None else "暂无")
        columns[3].metric("60 日年化波动", f"{volatility:.2f}%" if volatility is not None else "暂无")
        columns = st.columns(4)
        columns[0].metric("MA20", summary.get("ma20") or "暂无")
        columns[1].metric("MA60", summary.get("ma60") or "暂无")
        columns[2].metric("RSI14", summary.get("rsi14") or "暂无")
        average_amount = summary.get("avg_amount_20d")
        columns[3].metric(
            "20 日均成交额",
            f"{average_amount / 100_000_000:.2f} 亿元" if average_amount else "暂无",
        )
        benchmark = summary.get("benchmark_return_60d_pct")
        relative = summary.get("relative_strength_60d_pct")
        benchmark_text = f"{benchmark:.2f}%" if benchmark is not None else "暂无"
        relative_text = f"{relative:.2f} 个百分点" if relative is not None else "暂无"
        section_header("相对市场表现")
        text_panel("沪深300对照", f"沪深300近 60 日：{benchmark_text}\n个股相对强弱：{relative_text}")
        section_header("价格趋势", "前复权收盘价与 20 / 60 日移动平均线")
        st.line_chart(
            result.history[["close", "ma20", "ma60"]].rename(
                columns={"close": "收盘价", "ma20": "MA20", "ma60": "MA60"}
            )
        )
        with st.expander("查看最近 30 条行情"):
            recent = result.history[["open", "high", "low", "close", "volume", "amount"]].tail(30)
            recent.columns = ["开盘", "最高", "最低", "收盘", "成交量", "成交额"]
            st.dataframe(recent.sort_index(ascending=False), width="stretch")

    with news_tab:
        news = report.news
        section_header("新闻情绪概览", "DeepSeek 仅基于已获取新闻进行分析")
        columns = st.columns(3)
        columns[0].metric("整体情绪", news.overall_sentiment)
        columns[1].metric("情绪评分", f"{news.score:.2f}")
        columns[2].metric("分析新闻数", len(news.items))
        section_header("分析摘要")
        text_panel("新闻证据汇总", news.summary)
        if news.items:
            section_header("新闻明细", "按事件、情绪与影响周期整理")
            rows = [
                {
                    "发布时间": item.published_at,
                    "标题": item.title,
                    "事件": item.event_type,
                    "情绪": item.sentiment,
                    "影响": item.impact,
                    "置信度": item.confidence,
                    "依据": item.reason,
                    "来源": item.source,
                    "链接": item.url,
                }
                for item in news.items
            ]
            st.dataframe(
                rows,
                column_config={
                    "链接": st.column_config.LinkColumn("链接"),
                    "置信度": st.column_config.ProgressColumn(
                        "置信度", min_value=0, max_value=1, format="%.2f"
                    ),
                },
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("未获取到有效新闻，本次按新闻证据不足处理。")

    with strategy_tab:
        spec = report.best_strategy
        backtest = report.final_backtest
        section_header("最佳候选策略", "依据验证集综合评分选优，留出集仅用于最终评估")
        text_panel(f"{spec.name} · {spec.strategy_type}", spec.rationale)
        columns = st.columns(4)
        columns[0].metric("留出集收益率", f"{backtest.total_return_pct:.2f}%")
        columns[1].metric("年化收益率", f"{backtest.annual_return_pct:.2f}%")
        columns[2].metric("夏普比率", f"{backtest.sharpe:.2f}")
        columns[3].metric("最大回撤", f"{backtest.max_drawdown_pct:.2f}%")
        columns = st.columns(3)
        columns[0].metric("完整平仓交易", backtest.trade_count)
        columns[1].metric("胜率", f"{backtest.win_rate_pct:.2f}%")
        columns[2].metric("期末权益", f"¥{backtest.final_value:,.2f}")
        st.caption(f"留出集区间：{backtest.start_date} 至 {backtest.end_date}，未参与候选策略选优。")

        iteration_rows = [
            {
                "迭代": record.iteration,
                "策略": record.strategy.name,
                "类型": record.strategy.strategy_type,
                "快线": record.strategy.fast_window,
                "慢线": record.strategy.slow_window,
                "训练收益%": record.train.total_return_pct,
                "验证收益%": record.validation.total_return_pct,
                "验证夏普": record.validation.sharpe,
                "验证回撤%": record.validation.max_drawdown_pct,
                "验证通过": "是" if record.passed else "否",
            }
            for record in report.iterations
        ]
        section_header("有限迭代记录", "逐轮比较训练与验证表现，避免无限制搜索")
        st.dataframe(iteration_rows, hide_index=True, width="stretch")
        with st.expander("查看最佳策略完整参数"):
            st.json(spec.model_dump())

        section_header("历史回测买卖时间", "仅为留出集历史成交记录，不是未来日期预测")
        if backtest.trades:
            st.dataframe(backtest.trades, hide_index=True, width="stretch")
        else:
            st.info("留出集内没有完整平仓交易，因此没有可展示的历史买卖时间。")

    with risk_tab:
        risk = report.risk
        risk_label, tone = RISK_META[risk.status]
        status_banner(
            "INDEPENDENT RISK CONTROL",
            risk_label,
            risk.summary,
            tone,
            "风控后仓位上限",
            f"{risk.position_pct:.1%}",
            risk.status,
        )
        section_header("风险检查明细", "硬性阻断项优先于买入信号，退出信号不被阻断")
        risk_rows = [
            {"检查项": check.name, "状态": check.status, "说明": check.detail}
            for check in risk.checks
        ]
        st.dataframe(risk_rows, hide_index=True, width="stretch")

    with log_tab:
        section_header("运行日志", "完整记录各阶段、迭代轮次与耗时，便于审计和排查")
        log_rows = [
            {
                "时间": event.timestamp.strftime("%Y-%m-%d %H:%M:%S %z"),
                "级别": event.level,
                "阶段": event.stage,
                "迭代": event.iteration,
                "消息": event.message,
                "耗时ms": event.duration_ms,
            }
            for event in report.logs
        ]
        st.dataframe(log_rows, hide_index=True, width="stretch")
        with st.expander("查看文本日志"):
            st.code("\n".join(format_log(event) for event in report.logs), language="text")


inject_styles()
render_header()
analysis_started = False

with st.container(border=True):
    st.markdown(
        """
<div class="config-topline">
    <div><div class="config-eyebrow">RESEARCH SETUP</div><div class="config-title">研究配置</div></div>
    <div class="config-source">新浪行情&nbsp;&nbsp;·&nbsp;&nbsp;DeepSeek&nbsp;&nbsp;·&nbsp;&nbsp;Backtrader</div>
</div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("analysis_form"):
        input_columns = st.columns([0.95, 1.75, 0.72, 1.05, 0.95], vertical_alignment="bottom")
        with input_columns[0]:
            symbol = st.text_input(
                "股票代码", value="000001", max_chars=6, placeholder="6 位 A 股代码"
            )
        with input_columns[1]:
            api_key = st.text_input(
                "DeepSeek API Key",
                type="password",
                value=load_api_key(),
                placeholder="输入 API Key",
            )
        with input_columns[2]:
            save_key = st.form_submit_button("保存 Key", width="stretch")
        with input_columns[3]:
            max_iterations = st.slider("最大迭代次数", min_value=1, max_value=5, value=3)
        with input_columns[4]:
            submitted = st.form_submit_button("开始分析", type="primary", width="stretch")
        with st.expander("高级参数：初始资金、历史年限与风险偏好", expanded=False):
            advanced_columns = st.columns(3)
            with advanced_columns[0]:
                initial_cash = st.number_input(
                    "初始资金（元）",
                    min_value=10_000,
                    max_value=10_000_000,
                    value=100_000,
                    step=10_000,
                )
            with advanced_columns[1]:
                lookback_years = st.selectbox("历史行情年限", options=[2, 3, 4, 5], index=1)
            with advanced_columns[2]:
                risk_level = st.selectbox("风险偏好", options=["保守", "稳健", "积极"], index=1)
    st.markdown(
        '<div class="config-note">未保存时仅用于本次请求；点击“保存 Key”后使用 Windows 当前账户加密存储，不写入日志或研究报告。</div>',
        unsafe_allow_html=True,
    )

if save_key:
    try:
        save_api_key(api_key)
    except ValueError as exc:
        st.error(str(exc))
    except OSError:
        st.error("Key 保存失败，请检查当前 Windows 账户和本机存储权限")
    else:
        st.success("API Key 已加密保存，下次启动将自动加载。")
elif submitted:
    st.session_state.pop("analysis_result", None)
    try:
        request = AnalysisRequest(
            symbol=symbol,
            deepseek_api_key=api_key,
            max_iterations=max_iterations,
            initial_cash=float(initial_cash),
            lookback_years=lookback_years,
            risk_level=risk_level,
        )
    except ValidationError as exc:
        st.error(f"参数校验失败：{exc.errors()[0]['msg']}")
    else:
        analysis_started = True
        log_lines: list[str] = []
        progress_value_holder = [0]
        stage_placeholder = st.empty()
        progress = st.progress(0, text="等待任务启动")
        status = st.empty()
        log_placeholder = st.empty()
        with stage_placeholder:
            render_pipeline("MARKET")
        status.info("分析进行中，请保持页面打开。行情和 AI 请求可能需要一些时间。")

        def on_log(event: LogEvent) -> None:
            log_lines.append(format_log(event))
            stage_progress = {
                "INPUT": 5,
                "MARKET": 15,
                "NEWS": 30,
                "STRATEGY": 35,
                "BACKTEST": 70,
                "RISK": 90,
                "DONE": 100,
                "ERROR": 100,
            }
            current = stage_progress.get(event.stage, 10)
            if event.iteration and event.stage in {"STRATEGY", "BACKTEST"}:
                current = min(
                    85,
                    30
                    + int((event.iteration - 1) * 55 / request.max_iterations)
                    + (15 if event.stage == "BACKTEST" else 0),
                )
            progress_value_holder[0] = max(progress_value_holder[0], current)
            progress.progress(
                progress_value_holder[0], text=f"{event.stage}：{event.message}"
            )
            with stage_placeholder:
                render_pipeline(event.stage, completed=event.stage == "DONE")
            log_placeholder.code("\n".join(log_lines[-100:]), language="text")

        try:
            result = QuantEngine(request, callback=on_log).run()
        except Exception as exc:
            status.error(f"分析失败：{exc}")
        else:
            st.session_state["analysis_result"] = result
            status.success("研究完成，结果已展示在下方。")
            log_placeholder.empty()

result = st.session_state.get("analysis_result")
if result is not None:
    show_result(result)
elif not analysis_started:
    render_welcome()

st.markdown(
    '<div class="app-footer"><strong>研究声明</strong><br>仅供量化研究与学习，不构成投资建议，不会自动下单。历史回测不代表未来收益；买卖日期来自历史回测，当前操作仅按条件触发并需人工确认。</div>',
    unsafe_allow_html=True,
)
