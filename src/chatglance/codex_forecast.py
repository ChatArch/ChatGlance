"""Public 24h forecast data only; never execute source JavaScript or infer history."""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import math
import re
import time
from typing import Any

PUBLIC_RESET_SOURCE = "https://codexreset.org/"
FORECAST_TTL_SECONDS = 7200
MAX_PUBLIC_BODY_BYTES = 2_000_000


def forecast_snapshot(raw: Any, *, now: float) -> dict:
    """Validate source metadata and freshness, returning only safe audit fields."""
    result = {"source": PUBLIC_RESET_SOURCE, "horizon": "24h", "status": "missing",
              "probability_24h_percent": None, "source_updated_at": None}
    if raw is None:
        return result
    result["status"] = "invalid"
    if not isinstance(raw, dict):
        return result
    if (raw.get("source") != PUBLIC_RESET_SOURCE or raw.get("horizon") != "24h"
            or raw.get("stale") or raw.get("using_last_known_values")):
        return result
    probability = raw.get("probability_24h_percent")
    if type(probability) in (int, float) and math.isfinite(probability) and 0 <= probability <= 100:
        result["probability_24h_percent"] = probability
    updated = raw.get("source_updated_at")
    epoch = None
    if isinstance(updated, str):
        try:
            timestamp = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            if timestamp.tzinfo is not None:
                epoch = timestamp.timestamp()
                result["source_updated_at"] = timestamp.astimezone(timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    if raw.get("status") != "ok":
        result["status"] = "unavailable"
    elif result["probability_24h_percent"] is None or epoch is None:
        pass
    elif type(now) not in (int, float) or not math.isfinite(now):
        pass
    elif epoch > now:
        result["status"] = "future"
    elif now - epoch > FORECAST_TTL_SECONDS:
        result["status"] = "stale"
    else:
        result["status"] = "ok"
    return result


def _segments(text: str, delimiter: str = ","):
    """Split at code-level delimiters, discarding comments but not strings."""
    stack, quote, escaped, part, i = [], None, False, [], 0
    while i < len(text):
        char = text[i]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            elif quote == "`" and text.startswith("${", i):
                raise ValueError("Unsupported source template expression")
        elif text.startswith("//", i):
            end = re.search(r"[\r\n\u2028\u2029]|$", text[i + 2:])
            i += 2 + end.start()
            part.append(" ")
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError("Incomplete source comment")
            i = end + 2
            part.append(" ")
            continue
        elif char == "/":
            # Regex literals/division are outside this static SSR data adapter.
            raise ValueError("Unsupported source slash token")
        elif char in '\"\'`':
            quote = char
        elif char in "{[(":
            stack.append({"{": "}", "[": "]", "(": ")"}[char])
            if len(stack) > 64:
                raise ValueError("Source nesting limit")
        elif char in "}])":
            if not stack or stack.pop() != char:
                raise ValueError("Unbalanced source data")
        elif char == delimiter and not stack:
            yield "".join(part)
            part = []
            i += 1
            continue
        part.append(char)
        i += 1
    if stack or quote:
        raise ValueError("Incomplete source data")
    yield "".join(part)


def _literal_body(value: str, brackets: str) -> str:
    value = re.sub(r"^\$R\[\d+\]\s*=\s*", "", value.strip())
    if not value.startswith(brackets[0]) or not value.endswith(brackets[1]):
        raise ValueError("Expected a literal source container")
    return value[1:-1]


def _fields(value: str) -> dict[str, str]:
    fields = {}
    for part in _segments(_literal_body(value, "{}")):
        key, sep, raw = part.partition(":")
        key = key.strip()
        if key.startswith('"'):
            key = json.loads(key)
        if not sep or not re.fullmatch(r"[\w$]+", key) or key in fields:
            raise ValueError("Invalid or duplicate source member")
        fields[key] = raw.strip()
    return fields


class _InlineScripts(HTMLParser):
    """Collect inline JS outside comments and inert HTML, without building a DOM."""

    # Treat raw-text/RCDATA containers alike: neither can contain real scripts.
    # noscript is inert here because the source requires a JS-capable browser.
    CDATA_CONTENT_ELEMENTS = (
        "script", "style", "noscript", "textarea", "title", "xmp", "iframe",
        "noembed", "noframes",
    )
    _JS_TYPES = {"", "module", "text/javascript", "application/javascript",
                 "text/ecmascript", "application/ecmascript"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self._parts: list[str] | None = None
        self._template_depth = 0
        self._plaintext = False

    def parse_comment(self, i, report=1):
        # Older HTMLParser treats '-- >' as a terminator. HTML does not; keep
        # those bytes inside the comment on every supported Python version.
        end = re.compile(r"--!?>").search(self.rawdata, i + 4)
        if end is None:
            return -1
        if report:
            self.handle_comment(self.rawdata[i + 4:end.start()])
        return end.end()

    def handle_starttag(self, tag, attrs):
        if self._plaintext:
            return
        if tag == "plaintext":
            self._plaintext = True  # Even </plaintext> cannot reopen HTML parsing.
        elif tag == "template":
            self._template_depth += 1
        elif tag == "script" and not self._template_depth:
            attributes = {}
            for name, value in attrs:
                # HTML keeps the first duplicate, never an enabling later value.
                attributes.setdefault(name, value)
            if "src" in attributes or "nomodule" in attributes:
                return
            script_type = attributes.get("type") or ""
            if "type" not in attributes and attributes.get("language"):
                script_type = "text/" + attributes["language"]
            if script_type.strip("\t\n\f\r ").lower() in self._JS_TYPES:
                self._parts = []

    def handle_startendtag(self, tag, attrs):
        # In HTML, '/>' does not close these non-void elements. HTMLParser's
        # default start+end callbacks would wrongly re-enable an inert context.
        self.handle_starttag(tag, attrs)
        if tag in self.CDATA_CONTENT_ELEMENTS:
            self.set_cdata_mode(tag)

    def handle_endtag(self, tag):
        if self._plaintext:
            return
        if tag == "template":
            self._template_depth = max(0, self._template_depth - 1)
        elif tag == "script" and self._parts is not None:
            self.scripts.append("".join(self._parts))
            self._parts = None

    def handle_data(self, data):
        if self._parts is not None:
            self._parts.append(data)


def _snapshot_object(page: str) -> str:
    parser = _InlineScripts()
    parser.feed(page)
    parser.close()
    assignment = re.compile(r"\$_TSR\s*\.\s*router\s*=")
    statements = [statement.strip()
                  for script in parser.scripts
                  if "$_TSR" in script
                  for statement in _segments(script, ";")
                  if assignment.match(statement.strip())]
    if len(statements) != 1:
        raise ValueError("Missing or ambiguous source router")
    # Accept only the observed inline SSR root, not references or executable paths.
    root = re.fullmatch(
        r"\(\s*\$R\s*=>\s*(\$R\[\d+\]\s*=\s*\{.*\})\s*\)"
        r'\s*\(\s*\$R\["tsr"\]\s*\)',
        assignment.sub("", statements[0], count=1).strip(), re.S,
    )
    if root is None:
        raise ValueError("Unsupported source router")
    matches = _literal_body(_fields(root[1])["matches"], "[]")
    routes = [_fields(item) for item in _segments(matches)]
    current = [route for route in routes if json.loads(route["i"]) == "//"]
    if len(current) != 1 or json.loads(current[0]["s"]) != "success":
        raise ValueError("Missing or ambiguous successful home route")
    return _fields(current[0]["l"])["snapshot"]


def parse_public_forecast(page: str, *, now: float | None = None) -> dict:
    """Read only literal current snapshot fields from the site's SSR data.

    This is a deliberately narrow, fail-closed adapter, not a JS interpreter.
    Never substitute the animated gauge, baseline, prior score, or history.
    """
    now = time.time() if now is None else now
    invalid = {**forecast_snapshot(None, now=now), "status": "invalid"}
    try:
        if not isinstance(page, str) or len(page) > MAX_PUBLIC_BODY_BYTES:
            return invalid
        snapshot = _fields(_snapshot_object(page))
        if (json.loads(snapshot["status"]) != "live"
                or json.loads(snapshot["forecastStatus"]) != "current"):
            return invalid
        forecast = _fields(snapshot["forecast"])
        return forecast_snapshot({
            "source": PUBLIC_RESET_SOURCE, "horizon": "24h", "status": "ok",
            "probability_24h_percent": json.loads(forecast["score24h"]),
            "source_updated_at": json.loads(snapshot["updatedAt"]),
        }, now=now)
    except (KeyError, TypeError, ValueError, RecursionError):
        return invalid
