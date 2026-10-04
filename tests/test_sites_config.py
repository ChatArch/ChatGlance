from __future__ import annotations

import base64
import xml.etree.ElementTree as ET

import pytest
import yaml
from chatenv import EnvStore, get_paths

from chatglance.config import ChatGlanceConfig
from chatglance.sites import cover_data_uri, load_sites_inventory


KEYS = ("CHATGLANCE_SITES_PUBLIC_DOMAIN", "CHATGLANCE_SITES_LOCAL_DOMAIN", "CHATGLANCE_SITES_UPTIME_BASE_URL")


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def inventory(tmp_path, *, page=None, site=None):
    path = tmp_path / "sites.yml"
    path.write_text(yaml.safe_dump({"page": page or {}, "sites": [site or {"name": "demo"}]}))
    return path


def test_site_fields_are_typed_nonsecret_and_have_no_deployment_defaults():
    fields = ChatGlanceConfig.get_fields()
    assert set(KEYS).issubset(fields)
    for key in KEYS:
        assert fields[key].is_sensitive is False
        assert not fields[key].default


def test_service_urls_use_process_env_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv(KEYS[0], "public.example.org")
    monkeypatch.setenv(KEYS[1], "internal.example.org")
    monkeypatch.setenv(KEYS[2], "https://status.example.org/monitor/")
    item = load_sites_inventory(inventory(tmp_path))["sites"][0]
    assert item["public_url"] == "https://demo.public.example.org/"
    assert item["local_host"] == "demo.internal.example.org"
    assert item["uptime_url"] == "https://status.example.org/monitor/endpoints/chatarch-services_demo"


def test_missing_public_configuration_fails_instead_of_guessing_a_domain(tmp_path):
    with pytest.raises(ValueError, match="public_url|CHATGLANCE_SITES_PUBLIC_DOMAIN"):
        load_sites_inventory(inventory(tmp_path))


def test_explicit_service_url_needs_no_domain_or_monitor_config(tmp_path):
    data = load_sites_inventory(inventory(tmp_path, site={"name": "demo", "public_url": "https://portal.example.org/demo/"}))
    assert data["sites"][0]["public_url"] == "https://portal.example.org/demo/"
    assert data["sites"][0]["local_host"] == ""
    assert data["sites"][0]["uptime_url"] == ""
    assert data["counts"]["monitored"] == 0


def test_inventory_overrides_environment_and_service_overrides_inventory(tmp_path, monkeypatch):
    monkeypatch.setenv(KEYS[0], "env.example.org")
    monkeypatch.setenv(KEYS[1], "env-internal.example.org")
    monkeypatch.setenv(KEYS[2], "https://env-status.example.org/")
    page = {"public_domain": "page.example.org", "local_domain": "page-internal.example.org", "uptime_base_url": "https://page-status.example.org/"}
    item = load_sites_inventory(inventory(tmp_path, page=page))["sites"][0]
    assert item["public_url"] == "https://demo.page.example.org/"
    assert item["local_host"] == "demo.page-internal.example.org"
    assert item["uptime_url"].startswith("https://page-status.example.org/")
    site = {"name": "demo", "public_url": "https://custom.example.org/entry", "local_host": "custom-internal.example.org", "uptime_url": "https://custom-status.example.org/demo"}
    item = load_sites_inventory(inventory(tmp_path, page=page, site=site))["sites"][0]
    assert all(item[key] == site[key] for key in ("public_url", "local_host", "uptime_url"))


def test_active_chatenv_profile_and_process_env_precedence(tmp_path, monkeypatch):
    store = EnvStore(get_paths().envs_dir)
    store.save_active(ChatGlanceConfig, {KEYS[0]: "profile.example.org"})
    path = inventory(tmp_path)
    assert load_sites_inventory(path)["sites"][0]["public_url"] == "https://demo.profile.example.org/"
    monkeypatch.setenv(KEYS[0], "env.example.org")
    assert load_sites_inventory(path)["sites"][0]["public_url"] == "https://demo.env.example.org/"


@pytest.mark.parametrize("domain", ["https://example.org", "example.org/path", "example.org?key=x", "example.org bad"])
def test_public_domain_rejects_non_domain_values(tmp_path, monkeypatch, domain):
    monkeypatch.setenv(KEYS[0], domain)
    with pytest.raises(ValueError, match="domain"):
        load_sites_inventory(inventory(tmp_path))


def test_svg_label_follows_actual_public_url_without_query_or_fragment():
    uri = cover_data_uri({"name": "demo", "title": "A & B", "public_url": "https://portal.example.org:8443/tools/demo/?private=x#fragment"})
    raw = base64.b64decode(uri.split(",", 1)[1]).decode()
    text = " ".join(ET.fromstring(raw).itertext())
    assert "portal.example.org:8443/tools/demo" in text
    assert "demo.public." not in text
    assert "private" not in text
    assert "fragment" not in text
    assert "A & B" in text


def test_svg_without_public_url_does_not_invent_a_host():
    raw = base64.b64decode(cover_data_uri({"name": "demo"}).split(",", 1)[1]).decode()
    assert "demo.public." not in raw


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://user:secret@example.org/", "https://example.org/?key=value", "https://example.org/#fragment", "https://example.org/monitor/?", "https://example.org/monitor/#"])
def test_chatenv_test_rejects_invalid_uptime_base(monkeypatch, url):
    monkeypatch.setenv(KEYS[2], url)
    with pytest.raises(ValueError, match="CHATGLANCE_SITES_UPTIME_BASE_URL"):
        ChatGlanceConfig.test()


def test_chatenv_test_validates_domain_suffixes(monkeypatch):
    monkeypatch.setenv(KEYS[1], "https://example.org")
    with pytest.raises(ValueError, match="domain"):
        ChatGlanceConfig.test()


def test_cover_does_not_display_url_credentials():
    raw = base64.b64decode(cover_data_uri({"public_url": "https://operator:hidden@example.org/demo"}).split(",", 1)[1]).decode()
    assert "operator" not in raw
    assert "hidden" not in raw
    assert "example.org/demo" in raw



def test_explicit_empty_page_values_clear_environment_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv(KEYS[0], "public.example.org")
    monkeypatch.setenv(KEYS[1], "internal.example.org")
    monkeypatch.setenv(KEYS[2], "https://status.example.org/")
    data = load_sites_inventory(inventory(tmp_path, page={"local_domain": "", "uptime_base_url": ""}))
    assert data["sites"][0]["public_url"] == "https://demo.public.example.org/"
    assert data["sites"][0]["local_host"] == ""
    assert data["sites"][0]["uptime_url"] == ""
    assert data["counts"]["monitored"] == 0
