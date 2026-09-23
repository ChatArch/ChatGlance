"""Authenticated same-origin configuration and explicit manual reset control."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import hmac
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import yaml
from chatenv import EnvStore, get_paths
from .config import ChatGlanceConfig, collection_settings
from .codex_resets import _epoch, parse_policies
from .codex_forecast import forecast_snapshot
from .reset_control_view import CONTROL_CSP, render_control_page

POLICIES = "CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"



class ControlError(RuntimeError):
    def __init__(self, message, status=400):
        self.status = status
        super().__init__(message)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def glance_authenticator(runtime_home):
    """Delegate both anonymous-denial and cookie acceptance to Glance itself."""
    try:
        config = yaml.safe_load((Path(runtime_home) / "config/glance.yml").read_text())
        auth = config.get("auth") or {}
        server = config.get("server") or {}
        port = server.get("port", 8080)
        if not auth.get("users") or not auth.get("secret-key"):
            raise ValueError
        if server.get("host", "127.0.0.1") not in ("127.0.0.1", "localhost"):
            raise ValueError
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError):
        raise ControlError("Glance 本地登录配置不可用", 503) from None
    url = f"http://127.0.0.1:{port}/account-limits"
    opener = build_opener(ProxyHandler({}), _NoRedirect())

    def authenticate(cookie):
        try:
            request = Request(url, headers={"Cookie": cookie} if cookie else {})
            with opener.open(request, timeout=3) as response:
                return response.status == 200
        except HTTPError as error:
            challenged = error.code in (301, 302, 303, 401, 403)
            error.close()
            if not challenged:
                raise ControlError("登录校验服务暂不可用", 503) from None
            return False
        except (OSError, URLError, ValueError):
            raise ControlError("登录校验服务暂不可用", 503) from None

    return authenticate


class ControlApp:
    def __init__(
        self,
        *,
        runtime_home,
        public_origin,
        home=None,
        authenticate=None,
        diagnose=None,
    ):
        origin = urlsplit(public_origin)
        if (
            origin.scheme != "https"
            or not origin.netloc
            or origin.username
            or origin.password
            or origin.path
            or origin.query
            or origin.fragment
        ):
            raise ControlError("需要不含路径的 HTTPS 公共 origin")
        self.runtime_home = Path(runtime_home)
        self.public_origin = public_origin
        self.home = home
        self.store = EnvStore(get_paths(home).envs_dir)
        self.authenticate = authenticate or glance_authenticator(runtime_home)
        self.diagnose = diagnose
        self.tokens = {}
        self.lock = threading.RLock()

    def authorized(self, cookie):
        if not cookie or len(cookie) > 8192:
            return False
        try:
            # Never trust a 200 if the upstream has stopped requiring login.
            return not self.authenticate("") and bool(self.authenticate(cookie))
        except Exception:
            return False

    def flags(self, profile):
        try:
            values = self.store.load_active(ChatGlanceConfig)
            settings = collection_settings(home=self.home)
            policies = parse_policies(settings["reset_policies"])
            if profile not in policies:
                raise ControlError("未知账号", 404)
            state = {"profile": profile, "policy": asdict(policies[profile])}
            revision = hashlib.sha256(
                json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            return values, policies, revision
        except (OSError, ValueError, TypeError):
            raise ControlError("无法读取自动用卡配置", 503) from None

    def account(self, profile):
        fallback = {
            "profile": profile,
            "status": "error",
            "windows": [],
            "observed_at": None,
        }
        try:
            path = self.runtime_home / "data/account-limits.json"
            if path.stat().st_size > 2 * 1024 * 1024:
                return fallback
            data = json.loads(path.read_text())
            rows = data.get("codex", [])
            matches = [
                row
                for row in rows
                if isinstance(row, dict) and row.get("profile") == profile
            ]
            return matches[0] if len(matches) == 1 else fallback
        except (OSError, ValueError, TypeError, AttributeError):
            return fallback

    def token(self, cookie):
        now = time.monotonic()
        self.tokens = {
            key: value for key, value in self.tokens.items() if value[1] > now
        }
        if len(self.tokens) >= 128:
            self.tokens.pop(next(iter(self.tokens)))
        nonce = secrets.token_urlsafe(24)
        self.tokens[nonce] = (hashlib.sha256(cookie.encode()).hexdigest(), now + 600)
        return nonce

    def consume_token(self, cookie, token):
        saved = self.tokens.pop(token, None)
        actual = hashlib.sha256(cookie.encode()).hexdigest()
        if (
            not saved
            or saved[1] <= time.monotonic()
            or not hmac.compare_digest(saved[0], actual)
        ):
            raise ControlError("操作凭据已失效，请刷新小窗", 403)

    def page(self, profile, cookie):
        _, policies, revision = self.flags(profile)
        if profile not in policies:
            raise ControlError("未知账号", 404)
        diagnose = self.diagnose
        if diagnose is None:
            from .reset_decisions import diagnose_account

            diagnose = diagnose_account
        account = self.account(profile)
        # The checklist is a record of the scheduled refresh that collected this
        # snapshot. Opening the page must never create a later, display-only
        # decision that disagrees with that refresh or implies a new redemption.
        now = _epoch(account.get("observed_at")) or time.time()
        report = diagnose(account, policies[profile], execute_enabled=True, now=now)
        auto = (
            account.get("auto_reset")
            if isinstance(account.get("auto_reset"), dict)
            else {}
        )
        report["forecast"] = forecast_snapshot(auto.get("forecast"), now=now)
        report["forecast_threshold"] = policies[profile].skip_if_forecast_24h_above
        report["policy"] = asdict(policies[profile])
        token = self.token(cookie)
        return render_control_page(
            report,
            token,
            revision,
            overridden=POLICIES in os.environ,
        )

    def change(self, values, cookie, origin):
        if origin != self.public_origin:
            raise ControlError("拒绝跨站操作", 403)
        required = {"profile", "scope", "enabled", "csrf", "revision"}
        if not required <= values.keys() or values.keys() - required - {"confirm"}:
            raise ControlError("操作参数不完整")
        if values["scope"] != "account" or values["enabled"] not in (
            "true",
            "false",
        ):
            raise ControlError("仅支持显式开启或关闭")
        enabled = values["enabled"] == "true"
        if enabled and values.get("confirm") != "enable":
            raise ControlError("开启操作需要明确确认")
        with self.lock:
            self.consume_token(cookie, values["csrf"])
            current, policies, revision = self.flags(values["profile"])
            if values["profile"] not in policies:
                raise ControlError("未知账号", 404)
            if values["revision"] != revision:
                raise ControlError("配置已变化，请刷新后重试", 409)
            if POLICIES in os.environ:
                raise ControlError("存在进程环境覆写，网页不能修改有效设置", 409)
            updated = dict(current)
            key = POLICIES
            raw = json.loads(current.get(POLICIES, "{}"))
            raw[values["profile"]]["enabled"] = enabled
            updated[key] = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
            try:
                self.store.save_active(ChatGlanceConfig, updated)
                readback = self.store.load_active(ChatGlanceConfig)
                if readback.get(key) != updated[key] or any(
                    readback.get(k) != v for k, v in current.items() if k != key
                ):
                    raise ValueError
            except (OSError, ValueError, TypeError):
                raise ControlError("配置写入或回读失败，请刷新核对", 503) from None
            print(
                json.dumps(
                    {
                        "event": "reset-control-switch",
                        "profile": values["profile"],
                        "scope": values["scope"],
                        "enabled": enabled,
                        "verified": True,
                    }
                ),
                flush=True,
            )

    def use_credit(self, values, cookie, origin):
        if origin != self.public_origin:
            raise ControlError("拒绝跨站操作", 403)
        if set(values) != {"profile", "csrf", "confirm"} or values["confirm"] != "use-one-credit":
            raise ControlError("操作参数不完整")
        with self.lock:
            self.consume_token(cookie, values["csrf"])
        _, policies, _ = self.flags(values["profile"])
        policy = policies[values["profile"]]
        from .codex_collector import _managed_client_options, fetch_public_codex_reset
        from .codex_resets import scan_profile
        settings = collection_settings(home=self.home)
        try:
            options = _managed_client_options(settings, [values["profile"]])
            if options.get("token_service") != "CRS":
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise ControlError("账号映射不可用") from None
        if not policy.enabled:
            return {"state": "unmet", "reason": "disabled", "checked_at": _iso_time()}
        forecast = (fetch_public_codex_reset(3).get("forecast")
                    if policy.skip_if_forecast_24h_above is not None else None)
        row = scan_profile(values["profile"], policy=policy, execute=True,
                           home=self.home, timeout=8, forecast=forecast,
                           require_exact_credit=True, **options)
        auto = row["auto_reset"]
        status = auto["status"]
        reason = auto["reason"] if status == "conditions_not_met" else status
        allowed = {"reset_verified", "disabled", "query_failed", "no_credit",
                   "no_exact_credit", "conditions_not_met", "query_failed_or_stale",
                   "credits_unknown", "forecast_unavailable", "forecast_above_threshold",
                   "target_window_missing", "target_window_ambiguous", "cooldown",
                   "already_processed", "blocked_pending", "uncertain", "state_error",
                   "conditions_expired", "nothing_to_reset", "pending"}
        if reason not in allowed:
            reason = "unavailable"
        state = ("success" if reason == "reset_verified" else
                 "uncertain" if reason in {"uncertain", "blocked_pending", "state_error", "pending"}
                 else "unmet")
        return {"state": state, "reason": reason, "checked_at": row["observed_at"]}


def _iso_time():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def make_control_server(
    *,
    runtime_home,
    public_origin,
    host="127.0.0.1",
    port=5679,
    home=None,
    authenticate=None,
    diagnose=None,
):
    if host != "127.0.0.1" or type(port) is not int or not 0 <= port <= 65535:
        raise ControlError("控制服务只能监听 IPv4 loopback")
    app = ControlApp(
        runtime_home=runtime_home,
        public_origin=public_origin,
        home=home,
        authenticate=authenticate,
        diagnose=diagnose,
    )

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass

        def respond(
            self,
            status,
            body="",
            *,
            location=None,
            content_type="text/html; charset=utf-8",
        ):
            payload = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                CONTROL_CSP,
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(payload)

        def handle_error(self, error):
            self.respond(
                error.status,
                '<meta charset="utf-8"><p>'
                + escape(str(error))
                + '</p><a href="/account-limits" target="_top">返回订阅详情，重新打开小窗</a>',
            )

        def check_auth(self):
            cookie = self.headers.get("Cookie", "")
            if not app.authorized(cookie):
                raise ControlError("请先登录一览台后重新打开小窗", 401)
            return cookie

        def do_GET(self):
            try:
                target = urlsplit(self.path)
                if target.path == "/health":
                    self.respond(
                        200, '{"status":"ok"}', content_type="application/json"
                    )
                    return
                if target.path != "/":
                    raise ControlError("页面不存在", 404)
                cookie = self.check_auth()
                query = parse_qs(target.query, max_num_fields=2)
                if set(query) != {"profile"} or len(query["profile"]) != 1:
                    raise ControlError("请选择账号")
                self.respond(200, app.page(query["profile"][0], cookie))
            except ControlError as error:
                self.handle_error(error)
            except Exception:
                self.handle_error(ControlError("判据暂不可用，请稍后刷新", 503))

        def do_POST(self):
            try:
                target = urlsplit(self.path)
                if target.query or target.path not in ("/toggle", "/use-credit"):
                    raise ControlError("操作不存在", 404)
                cookie = self.check_auth()
                if (
                    self.headers.get("Content-Type", "").split(";")[0]
                    != "application/x-www-form-urlencoded"
                ):
                    raise ControlError("不支持的请求格式", 415)
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ControlError("请求长度无效", 413)
                raw = parse_qs(
                    self.rfile.read(length).decode(),
                    keep_blank_values=True,
                    max_num_fields=8,
                )
                if any(len(value) != 1 for value in raw.values()):
                    raise ControlError("不接受重复参数")
                values = {key: value[0] for key, value in raw.items()}
                if target.path == "/use-credit":
                    result = app.use_credit(values, cookie, self.headers.get("Origin"))
                    self.respond(200, json.dumps(result), content_type="application/json")
                else:
                    app.change(values, cookie, self.headers.get("Origin"))
                    self.respond(303, location="./?" + urlencode({"profile": values["profile"]}))
            except ControlError as error:
                if urlsplit(self.path).path == "/use-credit":
                    self.respond(error.status, '{"state":"unmet","reason":"invalid_request"}',
                                 content_type="application/json")
                else:
                    self.handle_error(error)
            except (ValueError, UnicodeError):
                if urlsplit(self.path).path == "/use-credit":
                    self.respond(400, '{"state":"unmet","reason":"invalid_request"}',
                                 content_type="application/json")
                else:
                    self.handle_error(ControlError("请求格式无效"))
            except Exception:
                if urlsplit(self.path).path == "/use-credit":
                    self.respond(503, '{"state":"uncertain","reason":"unavailable"}',
                                 content_type="application/json")
                else:
                    self.handle_error(ControlError("操作未完成，请刷新核对", 503))

    class Server(HTTPServer):
        allow_reuse_address = True

    server = Server((host, port), Handler)
    server.control_app = app
    return server


def serve_controls(*, runtime_home, public_origin, port=5679, home=None):
    server = make_control_server(
        runtime_home=runtime_home, public_origin=public_origin, port=port, home=home
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
