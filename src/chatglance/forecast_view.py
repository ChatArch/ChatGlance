"""Shared visual explanation of an experimental forecast, never authorization."""

from datetime import datetime, timedelta, timezone
from html import escape
import math

from .codex_forecast import PUBLIC_RESET_SOURCE

FORECAST_CSS = """
.reset-forecast{border:1px solid var(--color-separator,#27272f);border-left:2px solid var(--color-primary,#d9c38c);border-radius:4px;padding:10px 12px;margin:12px 0;background:transparent;color:var(--color-text-base,#8b8b9c);text-align:left;line-height:inherit;font-size:inherit}
.reset-forecast.is-veto{border-left-color:var(--color-negative,#e88282)}
.reset-forecast.is-unknown{border-left-color:var(--color-text-subdue,#777784)}
.reset-forecast-title{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:inherit;color:var(--color-text-highlight,#d6d6dc)}
.reset-forecast strong{font-size:inherit;font-weight:600;white-space:nowrap;color:var(--color-primary,#d9c38c)}
.reset-forecast p{margin:4px 0;font-size:inherit}.reset-forecast small{display:block;font-size:12px;color:var(--color-text-base-muted,#8b8b9c)}
.reset-forecast a{color:var(--color-primary,#d9c38c);text-decoration:none}
.forecast-notes summary{cursor:pointer;font-size:12px;color:var(--color-text-base-muted,#8b8b9c);list-style:none}
.forecast-notes summary:before{content:'› ';}.forecast-notes[open] summary:before{content:'⌄ ';}
"""


def source_time(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return "未知"
        return dt.astimezone(timezone(timedelta(hours=8))).strftime(
            "%m-%d %H:%M（北京时间）"
        )
    except (TypeError, ValueError, OverflowError):
        return "未知"


def render_forecast(forecast, threshold):
    forecast = forecast if isinstance(forecast, dict) else {}
    number = forecast.get("probability_24h_percent")
    valid = (
        forecast.get("status") == "ok"
        and type(number) in (int, float)
        and math.isfinite(number)
        and 0 <= number <= 100
    )
    configured = (
        type(threshold) in (int, float)
        and math.isfinite(threshold)
        and 0 <= threshold <= 100
    )
    value = f"{number:g}%" if valid else "—"
    if not configured:
        kind, message = "is-unknown", "未配置预测否决：仅展示，不参与执行判断"
    elif not valid:
        kind, message = "is-unknown", "预测不可用：暂停自动用卡"
    elif number > threshold:
        kind, message = "is-veto", "预测否决：不用卡"
    else:
        kind, message = "is-clear", "未触发预测否决：仍需其余条件全部通过"
    rule = (
        f"超过 {threshold:g}% 否决；缺失或超过2小时视为不可用。" if configured else ""
    )
    return (
        f'<aside class="reset-forecast {kind}" aria-label="未来24小时重置预测">'
        f'<div class="reset-forecast-title"><span>未来24小时重置预测</span><strong>{value}</strong></div>'
        f'<p>{message}</p><details class="forecast-notes"><summary>来源与说明</summary><small>{escape(rule)}</small>'
        f"<small>来源更新：{escape(source_time(forecast.get('source_updated_at')))}</small>"
        f'<small><a href="{PUBLIC_RESET_SOURCE}" target="_blank" rel="noopener noreferrer">codexreset.org</a> · 第三方实验性概率，不是官方保证；低概率不代表不会重置。</small></details></aside>'
    )
