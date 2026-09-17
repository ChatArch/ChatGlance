import importlib
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
            "--port",
            "5679",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["runtime_home"] == tmp_path and calls[0]["port"] == 5679


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
