"""Read-only presentation of execution readiness and explicit switch forms."""
from __future__ import annotations

import base64
import hashlib
from html import escape
import math
from urllib.parse import urlencode

from .forecast_view import FORECAST_CSS, render_forecast, source_time

# Only these fixed scripts are authorized by CSP hashes.
THEME_SCRIPT = """(() => {
  try {
    if (window.parent === window) return;
    const host = parent.document;
    const root = document.documentElement;
    const colors = ['--color-primary', '--color-positive', '--color-negative',
      '--color-background', '--color-widget-background', '--color-separator',
      '--color-text-base', '--color-text-highlight', '--color-text-subdue',
      '--color-text-base-muted', '--color-popover-border'];
    for (const original of host.querySelectorAll('link[rel="stylesheet"][href]')) {
      const url = new URL(original.href);
      if (url.origin !== location.origin || !url.pathname.startsWith('/static/')) continue;
      const link = document.createElement('link');
      link.rel = 'stylesheet'; link.href = url.href;
      document.head.prepend(link);
    }
    const sync = () => {
      const style = parent.getComputedStyle(host.documentElement);
      const body = parent.getComputedStyle(host.body);
      for (const key of colors) root.style.setProperty(key, style.getPropertyValue(key));
      document.body.style.fontFamily = body.fontFamily;
      document.body.style.fontSize = body.fontSize;
      document.body.style.lineHeight = body.lineHeight;
    };
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(host.documentElement, {attributes:true, attributeFilter:['style','class']});
    window.addEventListener('pagehide', () => observer.disconnect(), {once:true});
  } catch (_) { /* Standalone access uses the same restrained fallback theme. */ }
})();"""
_SCRIPT_HASH = base64.b64encode(hashlib.sha256(THEME_SCRIPT.encode()).digest()).decode()
MANUAL_SCRIPT = """(() => {
  const form = document.querySelector('#manual-credit');
  if (!form) return;
  const button = form.querySelector('button');
  const status = document.querySelector('#manual-status');
  const labels = {
    reset_verified: '成功：已确认用卡并重置额度', disabled: '未满足：账号未开启',
    no_credit: '未满足：没有可用重置卡', no_exact_credit: '未满足：卡片详情不可用',
    conditions_not_met: '未满足：额度或剩余时间不足',
    forecast_above_threshold: '未满足：预测超过上限',
    forecast_unavailable: '未满足：预测不可用',
    cooldown: '未满足：冷却中', already_processed: '未满足：本窗口已处理',
    blocked_pending: '结果待确认：已阻断再次用卡', uncertain: '结果待确认：请勿重试',
    invalid_request: '操作未获授权，请刷新页面',
  };
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (button.disabled || !window.confirm('重新检查当前账号，条件全部满足时最多使用一张重置卡。确定继续？')) return;
    button.disabled = true;
    status.textContent = '检查中…';
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 90000);
    try {
      const body = new URLSearchParams(new FormData(form));
      body.set('confirm', 'use-one-credit');
      const response = await fetch(form.action, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body, signal: abort.signal,
      });
      const result = await response.json();
      if (!response.ok && result.reason !== 'invalid_request') throw new Error('unavailable');
      const message = labels[result.reason] || (result.state === 'uncertain'
        ? '结果待确认：请勿重试' : '未满足：' + result.reason);
      status.textContent = message + (result.checked_at ? ' · 本次检查 ' + result.checked_at : '');
    } catch (_) {
      status.textContent = '结果待确认：网络超时或连接中断，请勿重试，刷新页面核对状态。';
    } finally {
      clearTimeout(timer);
    }
  });
  button.disabled = false;
})();"""
_MANUAL_HASH = base64.b64encode(hashlib.sha256(MANUAL_SCRIPT.encode()).digest()).decode()
CONTROL_CSP = (
    "default-src 'none'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
    f"script-src 'sha256-{_SCRIPT_HASH}' 'sha256-{_MANUAL_HASH}'; connect-src 'self'; "
    "form-action 'self'; frame-ancestors 'self'; base-uri 'none'"
)

CONTROL_CSS = """
:root{--color-primary:#d9c38c;--color-positive:#d9c38c;--color-negative:#e88282;--color-widget-background:#17171c;--color-separator:#27272f;--color-text-base:#8b8b9c;--color-text-highlight:#d6d6dc;--color-text-subdue:#777784}
html{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;padding:16px;font:13px/1.6 'JetBrains Mono',monospace;background:var(--color-widget-background);color:var(--color-text-base)}
h1,p{margin:0}h1,button,summary,label{font:inherit}h1{font-weight:500;color:var(--color-text-highlight)}
.heading{display:flex;justify-content:space-between;gap:12px;align-items:baseline;margin-bottom:12px}
.meta,.rule,.footer{font-size:12px;color:var(--color-text-base-muted,var(--color-text-subdue))}
.automation-status{padding:10px 12px;border:1px solid var(--color-separator);border-left:2px solid var(--color-primary);margin-bottom:12px}
.automation-status strong{font-size:inherit;font-weight:500;color:var(--color-text-highlight)}
.automation-status p{margin-top:3px}.automation-status.ready{border-left-color:var(--color-positive)}
.checklist-title{margin:14px 0 4px;color:var(--color-text-highlight);font-weight:500}
.execution-checks{border-top:1px solid var(--color-separator)}
.gate-row,.decision-row{margin:0;padding:7px 0;border:0;border-bottom:1px solid var(--color-separator)}
.gate-main{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:12px}
.control-title{color:var(--color-text-highlight)}.gate-name .meta{display:block}
.gate-main summary,.gate-disclosure>summary,.decision-row>summary{list-style:none;cursor:pointer}
summary::-webkit-details-marker{display:none}
.state{white-space:nowrap;font-size:inherit}.state.pass{color:var(--color-positive)}
.state.fail,.state.guarded{color:var(--color-negative)}.state.unknown{color:var(--color-text-base)}
button,.action{border:1px solid var(--color-separator);border-radius:4px;background:transparent;color:var(--color-primary);padding:3px 9px;font:inherit;cursor:pointer;text-align:center}
.confirmation{margin-top:10px;padding:10px;background:color-mix(in srgb,var(--color-primary) 5%,transparent);border:1px solid var(--color-separator)}
.confirmation p{font-size:12px}.confirmation label{display:block;margin:8px 0}.confirmation input{accent-color:var(--color-primary)}
.decision-row>summary{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:12px}
.check-label{min-width:0}.check-label:before{content:'›';display:inline-block;width:12px;color:var(--color-text-subdue)}
.decision-row[open] .check-label:before{content:'⌄'}
.check-value{color:var(--color-text-highlight);text-align:right;overflow-wrap:anywhere}
.decision-row .state{min-width:3em;text-align:right}.rule{padding:7px 0 0 12px}
.footer{margin-top:14px}.footer a{display:inline-block;margin-top:5px;color:var(--color-primary);text-decoration:none}
.warning{color:var(--color-negative)}
.manual-credit{margin-top:14px;padding:10px;border:1px solid var(--color-separator)}
.manual-credit p{margin:6px 0}.manual-credit button:disabled{opacity:.5;cursor:default}
@media(max-width:460px){body{padding:12px}.heading{flex-wrap:wrap;gap:2px}.decision-row>summary{gap:8px}.gate-main{gap:8px}.check-value{max-width:115px}}
"""


def _e(value):
    return escape(str(value if value is not None else "未知"), quote=True)


def _display_value(check, report):
    value, key = check.get("value"), check.get("key")
    if type(value) in (int, float) and math.isfinite(value):
        if key in ("used_percent", "forecast_probability"):
            return f"{value:g}%"
        if key == "remaining_seconds":
            return f"{value / 3600:.1f} 小时"
        if key == "snapshot_freshness":
            return f"{value / 60:.1f} 分钟"
        if key == "reset_credits":
            return f"{value:g} 张"
    if key == "forecast_freshness":
        return source_time(value).replace("（北京时间）", "")
    if key == "target_window" and value in ("primary_window", "secondary_window"):
        return "7天总额度" if report.get("policy", {}).get("target_window_seconds") == 604800 else value.replace("_window", "")
    if key == "ledger":
        return {"no_known_block": "无已知阻断", "ledger_unknown": "状态未确认（已阻断自动用卡）", "cooldown": "冷却中",
                "blocked_pending": "有未决请求（已阻断自动用卡）", "pending": "处理中（已阻断自动用卡）", "uncertain": "结果未确认（已阻断自动用卡）",
                "already_processed": "本窗口已处理"}.get(value, value)
    return value


def render_control_page(report, token, revision, *, overridden=False):
    profile, controls = report["profile"], report["controls"]
    paused = []

    if not controls["account_enabled"]:
        paused.append("本账号未允许自动用卡")
    state = "paused" if paused else "ready" if report.get("automatic_allowed") is True else "waiting"
    title = {"paused": "自动用卡已暂停", "waiting": "自动用卡已开启 · 等待条件", "ready": "自动用卡已就绪"}[state]
    business = "业务条件已满足" if report["business_eligible"] else "业务条件尚未满足"
    detail = "；".join(paused + [business])
    hidden = (f'<input type="hidden" name="profile" value="{_e(profile)}">'
              f'<input type="hidden" name="csrf" value="{_e(token)}">'
              f'<input type="hidden" name="revision" value="{_e(revision)}">')
    forms = []
    for scope, name, hint, active in [
        ("account", "自动用卡", "仅影响当前账号", controls["account_enabled"]),
    ]:
        gate_state = "pass" if active else "fail"
        caption = f'<span class="gate-name"><span class="control-title">{name}</span><span class="meta">{_e(hint)}</span></span>'
        badge = f'<b class="state {gate_state}">{"开启" if active else "关闭"}</b>'
        if overridden:
            content = f'<div class="gate-main">{caption}{badge}</div><p class="warning">由运行环境管理，网页不可修改。</p>'
        elif active:
            content = f'<div class="gate-main">{caption}{badge}<button type="submit" aria-label="关闭{name}">关闭</button></div>'
        else:
            warning = "开启后，本账号在条件全部满足时会自动使用重置卡，不影响其他账号。"
            content = (f'<details class="gate-disclosure"><summary class="gate-main" aria-label="开启{name}">{caption}{badge}<span class="action">开启</span></summary>'
                       f'<div class="confirmation"><p>{warning}这里不会立即兑换。</p>'
                       f'<label><input type="checkbox" name="confirm" value="enable" required> 我确认开启</label>'
                       f'<button type="submit" aria-label="确认开启{name}">确认开启</button></div></details>')
        forms.append(f'<form class="gate-row" data-check="{scope}" data-state="{gate_state}" method="post" action="toggle">{hidden}'
                     f'<input type="hidden" name="scope" value="{scope}"><input type="hidden" name="enabled" value="{"false" if active else "true"}">{content}</form>')
    labels = {"pass": "通过", "fail": "未通过", "unknown": "未通过", "inactive": "不适用", "guarded": "已阻断"}
    visible_checks = [
        check for check in report.get("checks", [])
        if check.get("key") != "snapshot_freshness"
    ]
    rows = "".join(
        f'<details class="decision-row" data-check="{_e(check["key"])}" data-state="{_e("fail" if check["state"] == "unknown" else check["state"])}">'
        f'<summary><span class="check-label">{_e(check["label"])}</span><span class="check-value">{_e(_display_value(check, report))}</span>'
        f'<span class="state {_e("fail" if check["state"] == "unknown" else check["state"])}">{_e(labels.get(check["state"], "未通过"))}</span></summary>'
        f'<p class="rule">{_e(check["rule"])}</p></details>' for check in visible_checks
    )
    observed = source_time(report.get("observed_at")).replace("（北京时间）", "")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>自动用卡设置</title>
<style>{FORECAST_CSS}{CONTROL_CSS}</style></head><body>
<header class="heading"><h1>{_e(profile)}</h1><span class="meta">上次计划检查 {_e(observed)}</span></header>
<section class="automation-status {state}" data-automation="{state}" role="status"><strong>{title}</strong><p class="meta">{_e(detail)}</p></section>
{render_forecast(report.get("forecast"), report.get("forecast_threshold"))}
<p class="checklist-title">执行清单 <span class="meta">· 点击条件查看要求</span></p>
<section class="execution-checks" aria-label="自动用卡执行清单">{"".join(forms)}{rows}</section>
<section class="manual-credit" aria-label="手动检查并用卡"><form id="manual-credit" method="post" action="use-credit">
<input type="hidden" name="profile" value="{_e(profile)}"><input type="hidden" name="csrf" value="{_e(token)}">
<button type="submit" disabled>检查并用卡</button></form>
<p class="meta">仅确认后重新查询本账号；条件满足才最多使用一张。结果不明时不会自动重试。</p>
<p id="manual-status" role="status" aria-live="polite">尚未手动检查</p></section>
<footer class="footer">自动用卡只会在一次计划刷新内：先读取额度和卡片，再在同一次刷新中判断并最多消费一次。查看或刷新本小窗不会兑换。<br><a href="?{_e(urlencode({"profile":profile}))}">刷新状态</a></footer>
<script>{THEME_SCRIPT}</script><script>{MANUAL_SCRIPT}</script></body></html>'''
