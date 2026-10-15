import importlib
from contextlib import nullcontext
from click.testing import CliRunner
from chatenv import EnvStore, get_paths
from chatglance.cli import main
from chatglance.config import ChatGlanceConfig


def test_control_cli_is_a_real_thin_server_entrypoint(tmp_path, monkeypatch):
    api = importlib.import_module("chatglance.reset_control")
    calls = []
    monkeypatch.setattr(api, "serve_controls", lambda **kwargs: calls.append(kwargs))
    result = CliRunner().invoke(
        main,
        [
            "account-limits",
            "control-serve",
            "--runtime-home",
            str(tmp_path),
            "--public-origin",
            "https://dashboard.example.invalid",
            "--host",
            "192.168.88.1",
            "--port",
            "5679",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls[0] == {
        "runtime_home": tmp_path,
        "public_origin": "https://dashboard.example.invalid",
        "host": "192.168.88.1",
        "port": 5679,
    }


def test_runtime_controls_uses_typed_private_host_and_default_remains_loopback(tmp_path, monkeypatch):
    from chatglance import managed, reset_control

    calls = []
    monkeypatch.setattr(
        managed,
        "runtime_environment",
        lambda *args, **kwargs: {
            "CHATGLANCE_PUBLIC_ORIGIN": "https://dashboard.example.invalid",
            "CHATGLANCE_CONTROL_HOST": "192.168.88.1",
            "CHATGLANCE_CONTROL_PORT": "15679",
        },
    )
    monkeypatch.setattr(managed, "effective_home", lambda root: nullcontext())
    monkeypatch.setattr(reset_control, "serve_controls", lambda **kwargs: calls.append(kwargs))

    result = CliRunner().invoke(main, ["runtime", "controls", "--runtime-home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert calls[0]["host"] == "192.168.88.1"
    assert ChatGlanceConfig.get_fields()["CHATGLANCE_CONTROL_HOST"].default == "127.0.0.1"


def test_runtime_controls_rejects_public_typed_bind_cleanly(tmp_path, monkeypatch):
    from chatglance import managed

    monkeypatch.setattr(
        managed,
        "runtime_environment",
        lambda *args, **kwargs: {
            "CHATGLANCE_PUBLIC_ORIGIN": "https://dashboard.example.invalid",
            "CHATGLANCE_CONTROL_HOST": "203.0.113.8",
            "CHATGLANCE_CONTROL_PORT": "15679",
        },
    )
    monkeypatch.setattr(managed, "effective_home", lambda root: nullcontext())

    result = CliRunner().invoke(main, ["runtime", "controls", "--runtime-home", str(tmp_path)])

    assert result.exit_code != 0
    assert "controls unavailable (ControlError)" in result.output


def test_control_path_flows_from_shared_schema_into_snapshot(tmp_path, monkeypatch):
    from chatglance.codex_collector import collect_account_limits
    import chatglance.codex_collector as collector

    assert "CHATGLANCE_ACCOUNT_LIMITS_CONTROL_PATH" in ChatGlanceConfig.get_fields()
    store = EnvStore(get_paths(tmp_path).envs_dir)
    store.save_active(
        ChatGlanceConfig, {"CHATGLANCE_ACCOUNT_LIMITS_CONTROL_PATH": "/_controls/"}
    )
    monkeypatch.setattr(
        collector,
        "scan_profile",
        lambda profile, **kw: {
            "profile": profile,
            "status": "ok",
            "windows": [],
            "reset_history": [],
        },
    )
    result = collect_account_limits(
        profiles="demo",
        output_path=tmp_path / "snapshot.json",
        no_public_reset=True,
        home=tmp_path,
        execute_resets=False,
    )
    assert result["reset_control_path"] == "/_controls/"
