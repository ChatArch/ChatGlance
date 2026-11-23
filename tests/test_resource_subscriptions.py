"""Read-only resource subscriptions: contract and native page regressions."""
import json

import pytest

from chatglance.account_limits import render_account_limits_html
from chatglance.resource_subscriptions import (
    ResourceFetchError, collect_resources, load_resource_config,
    normalize_package, query_aliyun_packages,
)


SOURCE = {"id": "shared-traffic", "type": "aliyun-shared-traffic", "enabled": True, "profile": "example"}
PACKAGE = {"InstanceId": "flowpack-example-1", "CommodityCode": "flowpack", "PackageType": "flowpack",
           "Remark": "公网共享流量", "Region": "cn-example", "DeductType": "Absolute", "Status": "Available",
           "TotalAmount": "100", "TotalAmountUnit": "GB", "RemainingAmount": "25", "RemainingAmountUnit": "GB",
           "EffectiveTime": "2026-11-01T00:00:00Z", "ExpiryTime": "2026-12-01T00:00:00Z"}
NOW = "2026-11-17T09:00:00Z"


def test_distribution_requires_explicit_profile_load_api():
    from pathlib import Path
    metadata = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert '"chatenv>=0.2.15,<0.3.0"' in metadata
    assert '"ChatTool>=7.1.6,<8.0.0"' in metadata
    assert '"alibabacloud-tea-openapi>=0.4.7,<0.5"' in metadata


def test_config_validates_entire_batch_before_collection(tmp_path):
    path = tmp_path / "resource-subscriptions.yml"
    path.write_text("sources:\n  - id: shared-traffic\n    type: aliyun-shared-traffic\n    enabled: true\n    profile: example\n")
    assert load_resource_config(path) == [SOURCE]
    for bad in ("enabled: yes", "enabled: 1", "profile: ../secret", "id: ../bad", "type: ecs-nic"):
        path.write_text("sources:\n  - id: shared-traffic\n    type: aliyun-shared-traffic\n    enabled: true\n    profile: example\n  - id: second\n    type: aliyun-shared-traffic\n    enabled: true\n    profile: example\n    " + bad + "\n")
        with pytest.raises(ValueError):
            load_resource_config(path)
    path.unlink()
    assert load_resource_config(path) == []


def test_disabled_source_never_fetches():
    source = {**SOURCE, "enabled": False}
    assert collect_resources([source], [], lambda _: pytest.fail("fetched"), now=NOW) == []


@pytest.mark.parametrize("change", [
    {"TotalAmount": "NaN"}, {"RemainingAmount": "-1"}, {"RemainingAmount": "101"},
    {"RemainingAmountUnit": "MB"}, {"TotalAmountUnit": "?"},
])
def test_invalid_quantities_fail_truthfully(change):
    with pytest.raises(ValueError):
        normalize_package({**PACKAGE, **change})


def test_depleted_package_reports_zero_bytes_in_gb_without_changing_amount():
    depleted = {**PACKAGE, "RemainingAmount": "0", "RemainingAmountUnit": "Byte"}
    result = normalize_package(depleted)
    assert result["total"] == 100 and result["remaining"] == 0
    assert result["used"] == 100 and result["unit"] == "GB"
    assert result["progress_percent"] == 100
    with pytest.raises(ValueError):
        normalize_package({**depleted, "RemainingAmount": "1"})


def test_one_resource_card_shows_two_balances_and_exhausted_count():
    other = {**PACKAGE, "InstanceId": "flowpack-example-2", "RemainingAmount": "56.45708"}
    exhausted = {**PACKAGE, "InstanceId": "flowpack-example-3",
                 "RemainingAmount": "0", "RemainingAmountUnit": "Byte"}
    resource = collect_resources([SOURCE], [], lambda _: [PACKAGE, other, exhausted], now=NOW)[0]
    assert resource["status"] == "ok" and len(resource["records"]) == 3
    html = render_account_limits_html({"generated_at": NOW, "resources": [resource], "codex": []})
    assert html.count('resource-card"') == 1
    assert html.count('class="limit-progress" aria-label="已用') == 2
    assert "56.45708 GB" in html and "25 GB" in html
    assert "另有 1 个已耗尽资源包" in html
    assert "flowpack-example-3" not in html


def test_pagination_reconciles_and_filters_shared_traffic():
    calls = []
    other = {**PACKAGE, "InstanceId": "storage-example", "CommodityCode": "storage", "PackageType": "storage"}
    second = {**PACKAGE, "InstanceId": "flowpack-example-2", "ExpiryTime": "2027-01-01T00:00:00Z"}
    def fetch(page, size):
        calls.append((page, size))
        return {"Code": "Success", "Success": True, "Data": {"TotalCount": "3", "PageNum": str(page), "PageSize": str(size),
            "Instances": {"Instance": [PACKAGE, other] if page == 1 else [second]}}}
    assert query_aliyun_packages(fetch, page_size=2) == [PACKAGE, second]
    assert calls == [(1, 2), (2, 2)]


def test_empty_valid_package_response_can_omit_instances():
    assert query_aliyun_packages(lambda page, size: {"Code": "Success", "Success": True,
        "Data": {"TotalCount": "0", "PageNum": "1", "PageSize": str(size)}}) == []


@pytest.mark.parametrize("count", [True, "-1", "01", "1.0", "", 300001])
def test_bad_documented_count_fails_closed(count):
    with pytest.raises(ResourceFetchError) as caught:
        query_aliyun_packages(lambda page, size: {"Code": "Success", "Success": True,
            "Data": {"TotalCount": count, "PageNum": str(page), "PageSize": str(size),
                     "Instances": {"Instance": []}}})
    assert caught.value.kind == "invalid_data"


@pytest.mark.parametrize("broken", ["short", "repeat", "drift", "page", "size", "oversize"])
def test_pagination_requires_complete_stable_unfiltered_rows(broken):
    other = {**PACKAGE, "InstanceId": "storage-example"}
    last = {**PACKAGE, "InstanceId": "flowpack-example-2"}
    def fetch(page, size):
        rows = [PACKAGE, other] if page == 1 else [last]
        total = "3"
        number, advertised_size = str(page), str(size)
        if broken == "short" and page == 1: rows = [PACKAGE]
        if broken == "repeat" and page == 2: rows = [PACKAGE]
        if broken == "drift" and page == 2: total = "4"
        if broken == "page" and page == 2: number = "1"
        if broken == "size" and page == 2: advertised_size = "3"
        if broken == "oversize" and page == 1: rows = [PACKAGE, other, last]
        return {"Code": "Success", "Success": True,
                "Data": {"TotalCount": total, "PageNum": number, "PageSize": advertised_size,
                "Instances": {"Instance": rows}}}
    with pytest.raises(ResourceFetchError) as caught:
        query_aliyun_packages(fetch, page_size=2)
    assert caught.value.kind == "invalid_data"


@pytest.mark.parametrize("code,success,kind", [
    ("NotAuthorized", False, "permission_denied"),
    ("InvalidAccessKeyId.NotFound", False, "auth_error"),
    ("SystemError", False, "invalid_data"),
    ("NotAuthorized", True, "permission_denied"),
])
def test_http_200_business_failure_never_becomes_empty(code, success, kind):
    with pytest.raises(ResourceFetchError) as caught:
        query_aliyun_packages(lambda page, size: {"Code": code, "Success": success,
            "Message": "AKIA-RAW-CANARY", "Data": {"TotalCount": "0",
                "PageNum": str(page), "PageSize": str(size)}})
    assert caught.value.kind == kind
    assert caught.value.__context__ is None and caught.value.__cause__ is None


@pytest.mark.parametrize("field,value", [
    ("Code", None), ("Code", False), ("Success", None), ("Success", False),
    ("PageNum", None), ("PageNum", "2"), ("PageSize", None), ("PageSize", "1"),
])
def test_success_requires_complete_matching_protocol(field, value):
    def fetch(page, size):
        body = {"Code": "Success", "Success": True,
                "Data": {"TotalCount": "0", "PageNum": str(page), "PageSize": str(size)}}
        target = body["Data"] if field.startswith("Page") else body
        if value is None:
            del target[field]
        else:
            target[field] = value
        return body
    with pytest.raises(ResourceFetchError) as caught:
        query_aliyun_packages(fetch)
    assert caught.value.kind == "invalid_data"


def test_success_empty_permission_and_stale_are_distinct():
    success = collect_resources([SOURCE], [], lambda _: [PACKAGE], now=NOW)[0]
    assert success["status"] == "ok" and success["records"][0]["used"] == 75
    assert success["records"][0]["progress_percent"] == 75
    assert success["last_successful_at"] == NOW
    empty = collect_resources([SOURCE], [], lambda _: [], now=NOW)[0]
    assert empty["status"] == "empty" and empty["records"] == []
    def denied(_):
        raise ResourceFetchError("permission_denied")
    unknown = collect_resources([SOURCE], [], denied, now=NOW)[0]
    assert unknown["status"] == "permission_denied" and unknown["records"] == []
    assert unknown["last_successful_at"] is None
    stale = collect_resources([SOURCE], [success], denied, now="2026-11-18T09:00:00Z")[0]
    assert stale["stale"] and stale["checked_at"] != stale["last_successful_at"]
    assert stale["records"] == success["records"]


def test_stale_cache_is_bound_and_revalidated():
    success = collect_resources([SOURCE], [], lambda _: [PACKAGE], now=NOW)[0]
    def denied(_):
        raise ResourceFetchError("permission_denied")
    changed_profile = collect_resources([{**SOURCE, "profile": "other"}], [success], denied, now="2026-11-18T09:00:00Z")[0]
    assert changed_profile["records"] == [] and changed_profile["last_successful_at"] is None
    changed_type = collect_resources([{**SOURCE, "type": "other-read-only"}], [success], denied, now="2026-11-18T09:00:00Z")[0]
    assert changed_type["records"] == []
    poisoned = json.loads(json.dumps(success))
    poisoned["records"][0]["unit"] = "?"
    poisoned["records"][0]["secret"] = "AKIA-CANARY"
    rejected = collect_resources([SOURCE], [poisoned], denied, now="2026-11-18T09:00:00Z")[0]
    assert rejected["records"] == [] and not rejected["stale"]
    valid_extra = json.loads(json.dumps(success))
    valid_extra["records"][0]["secret"] = "AKIA-CANARY"
    retained = collect_resources([SOURCE], [valid_extra], denied, now="2026-11-18T09:00:00Z")[0]
    assert retained["stale"] and retained["last_successful_at"] == NOW
    assert "AKIA-CANARY" not in json.dumps(retained)


def test_malformed_date_never_serializes_raw_value():
    data = collect_resources([SOURCE], [], lambda _: [{**PACKAGE, "ExpiryTime": "AKIA-RAW-CANARY"}], now=NOW)
    assert data[0]["status"] == "invalid_data" and data[0]["records"] == []
    assert "AKIA-RAW-CANARY" not in json.dumps(data)


def test_generic_card_escapes_and_strips_secrets_without_controls():
    success = collect_resources([SOURCE], [], lambda _: [PACKAGE], now=NOW)[0]
    success["records"][0]["label"] = "<img src=x onerror=alert(1)>"
    success["secret"] = "CANARY-SECRET"
    html = render_account_limits_html({"generated_at": NOW, "resources": [success], "codex": []})
    assert "&lt;img" in html and "<img" not in html
    assert "CANARY-SECRET" not in html
    assert "公网共享流量" in html and "账号级" in html
    assert "75.0%" in html and "<details class=\"reset-card-panel\"" not in html
    denied = collect_resources([SOURCE], [], lambda _: (_ for _ in ()).throw(ResourceFetchError("permission_denied")), now=NOW)[0]
    html = render_account_limits_html({"resources": [denied], "codex": []})
    assert "权限不足，当前用量未知" in html
    assert "width: 0%" not in html


def test_raw_errors_and_credentials_cannot_enter_snapshot():
    def bad(_):
        raise ResourceFetchError("auth_error", "AKIA-CANARY raw sdk body")
    data = collect_resources([SOURCE], [], bad, now=NOW)
    assert "AKIA-CANARY" not in json.dumps(data)


def test_zero_total_has_no_invented_progress():
    source = collect_resources([SOURCE], [], lambda _: [{**PACKAGE, "TotalAmount": "0", "RemainingAmount": "0"}], now=NOW)[0]
    assert source["records"][0]["progress_percent"] is None
    html = render_account_limits_html({"resources": [source], "codex": []})
    assert "已用 0.0%" not in html


def test_fractional_amounts_keep_provider_precision():
    source = collect_resources([SOURCE], [], lambda _: [{**PACKAGE, "TotalAmount": "1.2345", "RemainingAmount": "0.2345"}], now=NOW)[0]
    record = source["records"][0]
    assert record["total"] == "1.2345" and record["remaining"] == "0.2345"
    assert "1.2345 GB" in render_account_limits_html({"resources": [source], "codex": []})


def test_resource_only_native_page_does_not_collect_codex_or_calendar(tmp_path, monkeypatch):
    from chatglance import refresh as pipeline, resource_subscriptions, codex_collector, config
    root = tmp_path / "runtime"
    (root / "config").mkdir(parents=True)
    (root / "config/resource-subscriptions.yml").write_text(
        "sources:\n  - id: shared-traffic\n    type: aliyun-shared-traffic\n    enabled: true\n    profile: example\n")
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(config, "collection_settings", lambda **kw: {"subscriptions": None})
    monkeypatch.setattr(codex_collector, "collect_account_limits", lambda **kw: pytest.fail("Codex or calendar fetched"))
    monkeypatch.setattr(resource_subscriptions, "fetch_aliyun_shared_traffic", lambda _: [PACKAGE])
    update = pipeline._collect_page("account-limits", root, stage, profiles=[], actual_cli_tree=False,
                                    allow_offline_regression=False, scheduled=False)
    assert update.data["resources"][0]["records"][0]["remaining"] == 25
    assert update.data["codex"] == []
    assert update.page["slug"] == "account-limits"
    assert not update.partial


def test_absent_config_preserves_legacy_codex_resource_rows(tmp_path, monkeypatch):
    from chatglance import refresh as pipeline, codex_collector, config
    root = tmp_path / "runtime"
    (root / "data").mkdir(parents=True)
    (root / "data/account-limits.json").write_text(json.dumps({"resources": [{"type": "aliyun-shared-traffic", "id": "old"}]}))
    monkeypatch.setattr(config, "collection_settings", lambda **kw: {"subscriptions": None})
    legacy = {"kind": "codex", "profiles": ["work"], "label": "legacy metadata"}
    monkeypatch.setattr(codex_collector, "collect_account_limits", lambda **kw: {
        "codex": [], "codex_reset": {"status": "skipped", "events": []}, "resources": [legacy]})
    update = pipeline._collect_page("account-limits", root, tmp_path, profiles=["work"],
        actual_cli_tree=False, allow_offline_regression=False, scheduled=False)
    assert update.data["resources"] == [legacy]


def test_invalid_config_fails_before_profile_lookup(tmp_path, monkeypatch):
    from chatglance import refresh as pipeline, config
    root = tmp_path / "runtime"
    (root / "config").mkdir(parents=True)
    (root / "config/resource-subscriptions.yml").write_text("sources:\n  - id: bad/path\n")
    monkeypatch.setattr(config, "collection_settings", lambda **kw: pytest.fail("credential lookup"))
    with pytest.raises(ValueError):
        pipeline._collect_page("account-limits", root, tmp_path, profiles=[], actual_cli_tree=False,
                               allow_offline_regression=False, scheduled=False)


def test_instance_projection_excludes_account_level_resources():
    from chatglance.instances import scope_account_data
    scoped = scope_account_data({"codex": [], "resources": [{"id": "shared-traffic", "records": [PACKAGE]}]}, ())
    assert scoped["resources"] == []


def test_official_sdk_query_is_read_only_and_bounded(monkeypatch):
    from chatglance import resource_subscriptions as resources
    from alibabacloud_tea_openapi import client as tea_client
    calls = []
    monkeypatch.setattr(resources, "_aliyun_profile", lambda profile: ("synthetic-id", "synthetic-secret"))
    class Client:
        def __init__(self, config):
            assert config.endpoint == "business.aliyuncs.com"
            assert config.protocol == "HTTPS"
        def call_api(self, params, request, runtime):
            calls.append((params, request, runtime))
            return {"body": {"Code": "Success", "Success": True,
                    "Data": {"TotalCount": "1", "PageNum": "1", "PageSize": "300",
                             "Instances": {"Instance": [PACKAGE]}}}}
    monkeypatch.setattr(tea_client, "Client", Client)
    assert resources.fetch_aliyun_shared_traffic(SOURCE) == [PACKAGE]
    params, request, runtime = calls[0]
    assert (params.action, params.version, params.method) == ("QueryResourcePackageInstances", "2017-12-14", "GET")
    assert request.query == {"PageNum": "1", "PageSize": "300"}
    assert runtime.connect_timeout == 5000 and runtime.read_timeout == 15000


def test_sdk_exception_context_does_not_hold_raw_body(monkeypatch):
    from chatglance import resource_subscriptions as resources
    from alibabacloud_tea_openapi import client as tea_client
    monkeypatch.setattr(resources, "_aliyun_profile", lambda profile: ("synthetic-id", "synthetic-secret"))
    class RawError(Exception):
        code = "NotAuthorized"
    class Client:
        def __init__(self, config): pass
        def call_api(self, params, request, runtime):
            raise RawError("AKIA-RAW-CANARY")
    monkeypatch.setattr(tea_client, "Client", Client)
    with pytest.raises(ResourceFetchError) as caught:
        resources.fetch_aliyun_shared_traffic(SOURCE)
    assert caught.value.kind == "permission_denied"
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert "AKIA-RAW-CANARY" not in str(caught.value)
