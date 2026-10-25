"""Raw sensitive Env login through the original native Go auth fields."""
import base64
import json

import pytest
import yaml
from chatenv import EnvStore, get_paths

from chatglance.config import ChatGlanceConfig
from chatglance.instances import configure_instance, initialize_instance, instance_environment, load_instance, set_instance_login
from chatglance.managed import runtime_environment
from chatglance.portable import authenticated_environment
from test_instances import initialized, named_values, spec


def test_raw_login_field_roundtrip_and_native_instance_template(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    root = initialized(tmp_path)
    store = EnvStore(get_paths().envs_dir)
    password = "six:line\n雪m6"
    assert ChatGlanceConfig.get_fields()["CHATGLANCE_LOGIN_PASSWORD"].is_sensitive
    old_config = yaml.safe_load((root / "config/glance.yml").read_text())
    assert "password-hash" in next(iter(old_config["auth"]["users"].values()))

    result = set_instance_login(root, username="reader@example.invalid", password=password, apply=True)
    values = store.load_profile(ChatGlanceConfig, "teacher")
    assert values["CHATGLANCE_LOGIN_PASSWORD"] == password
    assert "CHATGLANCE_LOGIN_PASSWORD_HASH" not in values
    assert "CHATGLANCE_LOGIN_PASSWORD_YAML" not in values
    assert len(base64.b64decode(values["CHATGLANCE_LOGIN_SECRET"])) == 64
    config_text = (root / "config/glance.yml").read_text()
    config = yaml.safe_load(config_text)
    assert next(iter(config["auth"]["users"].values())) == {
        "password": "${CHATGLANCE_LOGIN_PASSWORD_YAML}"}
    assert password not in config_text and password not in json.dumps(result)
    environment = instance_environment(root, auth=True)
    assert json.loads(environment["CHATGLANCE_LOGIN_PASSWORD_YAML"]) == password
    assert "CHATGLANCE_LOGIN_PASSWORD_HASH" not in environment
    assert "CHATGLANCE_LOGIN_PASSWORD" not in environment


def test_raw_bridge_uses_internal_yaml_scalar_and_legacy_hash_stays_valid():
    secret = base64.b64encode(bytes(range(64))).decode()
    common = {"CHATGLANCE_LOGIN_SECRET": secret, "CHATGLANCE_LOGIN_USER": "reader@example.invalid",
              "CHATGLANCE_WEB_PORT": "11080"}
    password = "pass:quote'\\\n雪m6"
    raw = authenticated_environment(environ={**common, "CHATGLANCE_LOGIN_PASSWORD": password,
        "CHATGLANCE_LOGIN_PASSWORD_HASH": "$2b$12$" + "A" * 53}, strict=True)
    assert json.loads(raw["CHATGLANCE_LOGIN_PASSWORD_YAML"]) == password
    assert "雪" not in raw["CHATGLANCE_LOGIN_PASSWORD_YAML"]
    assert "\n" not in raw["CHATGLANCE_LOGIN_PASSWORD_YAML"]
    assert "CHATGLANCE_LOGIN_PASSWORD" not in raw
    assert "CHATGLANCE_LOGIN_PASSWORD_HASH" not in raw
    legacy = authenticated_environment(environ={**common,
        "CHATGLANCE_LOGIN_PASSWORD_HASH": "$2b$12$" + "A" * 53}, strict=True)
    assert legacy["CHATGLANCE_LOGIN_PASSWORD_HASH"].startswith("$2b$")
    assert "CHATGLANCE_LOGIN_PASSWORD_YAML" not in legacy
    for invalid in ("five5", "x" * 73):
        with pytest.raises(ValueError):
            authenticated_environment(environ={**common, "CHATGLANCE_LOGIN_PASSWORD": invalid}, strict=True)


def test_raw_instance_selection_survives_configure_and_never_uses_active(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    root = initialized(tmp_path)
    store = EnvStore(get_paths().envs_dir)
    store.save_active(ChatGlanceConfig, named_values(user="main@example.invalid", seed=b"M"))
    monkeypatch.setenv("CHATGLANCE_LOGIN_PASSWORD", "poison-process-password")
    set_instance_login(root, username="reader@example.invalid", password="raw-instance-password", apply=True)
    before = store.load_profile(ChatGlanceConfig, "teacher")
    configured = configure_instance(root, spec(accounts=("alpha",)), apply=True)
    assert configured["applied"] and load_instance(root).accounts == ("alpha",)
    assert "password: ${CHATGLANCE_LOGIN_PASSWORD_YAML}" in (root / "config/glance.yml").read_text()
    environment = runtime_environment(root, auth=True)
    assert json.loads(environment["CHATGLANCE_LOGIN_PASSWORD_YAML"]) == "raw-instance-password"
    assert environment["CHATGLANCE_LOGIN_USER"] == "reader@example.invalid"
    assert store.load_profile(ChatGlanceConfig, "teacher") == before
    assert store.load_active(ChatGlanceConfig)["CHATGLANCE_LOGIN_USER"] == "main@example.invalid"


def test_init_uses_prepopulated_raw_named_profile_without_set_login(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    store = EnvStore(get_paths().envs_dir)
    values = named_values()
    values["CHATGLANCE_LOGIN_PASSWORD"] = "native-env-password-雪"
    store.save_profile(ChatGlanceConfig, "teacher", values)
    store.save_active(ChatGlanceConfig, named_values(user="main@example.invalid", seed=b"M"))
    monkeypatch.setenv("CHATGLANCE_LOGIN_PASSWORD", "poison-process-password")
    root = tmp_path / "teacher-runtime"

    initialize_instance(root, spec(), apply=True)

    config = yaml.safe_load((root / "config/glance.yml").read_text())
    assert next(iter(config["auth"]["users"].values())) == {
        "password": "${CHATGLANCE_LOGIN_PASSWORD_YAML}"}
    environment = instance_environment(root, auth=True)
    assert json.loads(environment["CHATGLANCE_LOGIN_PASSWORD_YAML"]) == values["CHATGLANCE_LOGIN_PASSWORD"]
    assert "CHATGLANCE_LOGIN_PASSWORD_HASH" not in environment


def test_configure_selects_new_raw_credential_from_bound_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    root = initialized(tmp_path)
    store = EnvStore(get_paths().envs_dir)
    values = store.load_profile(ChatGlanceConfig, "teacher")
    values["CHATGLANCE_LOGIN_PASSWORD"] = "configured-env-password"
    store.save_profile(ChatGlanceConfig, "teacher", values)
    monkeypatch.setenv("CHATGLANCE_LOGIN_PASSWORD", "poison-process-password")

    configure_instance(root, spec(accounts=("alpha",)), apply=True)

    config = yaml.safe_load((root / "config/glance.yml").read_text())
    assert next(iter(config["auth"]["users"].values())) == {
        "password": "${CHATGLANCE_LOGIN_PASSWORD_YAML}"}
    environment = instance_environment(root, auth=True)
    assert json.loads(environment["CHATGLANCE_LOGIN_PASSWORD_YAML"]) == values["CHATGLANCE_LOGIN_PASSWORD"]


@pytest.mark.parametrize("previous_raw", (False, True))
def test_raw_login_template_publication_failure_restores_named_profile(tmp_path, monkeypatch, previous_raw):
    from chatglance import instances
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    root = initialized(tmp_path)
    store = EnvStore(get_paths().envs_dir)
    if previous_raw:
        set_instance_login(root, username="reader@example.invalid", password="old-raw-password", apply=True)
    before = store.load_profile(ChatGlanceConfig, "teacher")
    config = root / "config/glance.yml"
    old_config = config.read_bytes()
    monkeypatch.setattr("chatglance.refresh._publish", lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic publication failure")))
    with pytest.raises(OSError):
        instances.set_instance_login(root, username="reader@example.invalid", password="new-raw-password", apply=True)
    assert store.load_profile(ChatGlanceConfig, "teacher") == before
    assert config.read_bytes() == old_config


def test_unsupported_chatenv_roundtrip_restores_original_values(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    root = initialized(tmp_path)
    store = EnvStore(get_paths().envs_dir)
    profile_path = store.profile_path(ChatGlanceConfig, "teacher")
    config_path = root / "config/glance.yml"
    before = store.load_profile(ChatGlanceConfig, "teacher")
    profile_bytes, config_bytes = profile_path.read_bytes(), config_path.read_bytes()
    password = "can't-roundtrip-here"
    observed = []
    original_save = EnvStore.save_profile

    def record_save(self, config_cls, name, values=None):
        if name == "teacher":
            observed.append(dict(values))
        return original_save(self, config_cls, name, values)

    monkeypatch.setattr(EnvStore, "save_profile", record_save)
    with pytest.raises(ValueError, match="did not round-trip through ChatEnv") as error:
        set_instance_login(root, username="reader@example.invalid", password=password, apply=True)
    assert password not in str(error.value)
    assert len(observed) == 2
    assert observed[0]["CHATGLANCE_LOGIN_PASSWORD"] == password
    assert observed[1] == before
    assert store.load_profile(ChatGlanceConfig, "teacher") == before
    assert profile_path.read_bytes() == profile_bytes
    assert config_path.read_bytes() == config_bytes


def test_hash_only_indexed_account_ignores_raw_primary(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    root = tmp_path / "legacy-runtime"
    root.mkdir()
    values = named_values()
    values["CHATGLANCE_LOGIN_PASSWORD"] = "raw-primary-password"
    values["CHATGLANCE_LOGIN_ACCOUNTS"] = json.dumps({"0": {"username": "indexed@example.invalid",
        "password_hash": "$2b$12$" + "A" * 53}})
    EnvStore(get_paths().envs_dir).save_active(ChatGlanceConfig, values)
    environment = runtime_environment(root, auth=False)
    assert environment["CHATGLANCE_AUTH_USER_0"] == "indexed@example.invalid"
    assert environment["CHATGLANCE_AUTH_HASH_0"] == "$2b$12$" + "A" * 53
    assert "CHATGLANCE_LOGIN_PASSWORD_YAML" not in environment
    assert "CHATGLANCE_LOGIN_PASSWORD" not in environment


def test_raw_instance_missing_password_fails_closed_without_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    root = initialized(tmp_path)
    store = EnvStore(get_paths().envs_dir)
    set_instance_login(root, username="reader@example.invalid", password="initial-raw-password", apply=True)
    values = store.load_profile(ChatGlanceConfig, "teacher")
    values.pop("CHATGLANCE_LOGIN_PASSWORD")
    store.save_profile(ChatGlanceConfig, "teacher", values)
    profile_path = store.profile_path(ChatGlanceConfig, "teacher")
    config_path = root / "config/glance.yml"
    before = (profile_path.read_bytes(), config_path.read_bytes())
    monkeypatch.setenv("CHATGLANCE_LOGIN_PASSWORD", "poison-process-password")
    with pytest.raises(ValueError, match="native raw login password is missing"):
        instance_environment(root, auth=True)
    assert (profile_path.read_bytes(), config_path.read_bytes()) == before


def test_raw_password_validation_has_no_secret_in_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    root = initialized(tmp_path)
    for password in ("s:3'", "雪", "canary-secret-" + "x" * 70, "canary-secret-\x00inside"):
        with pytest.raises(ValueError) as error:
            set_instance_login(root, username="reader@example.invalid", password=password, apply=True)
        assert password not in str(error.value)
