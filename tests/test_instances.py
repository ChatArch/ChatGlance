"""Isolated read-only instances reuse page modules; no live service data."""
import base64
import importlib.util
import json
from pathlib import Path
import sys

import bcrypt
import pytest
import yaml
from click.testing import CliRunner
from chatenv import EnvStore, get_paths
from chatglance.config import ChatGlanceConfig, collection_settings
from chatglance.cli import main
from chatglance import refresh
from test_subscriptions import install_clients
from test_codex_resets import NOW

SUBS = "CHATGLANCE_ACCOUNT_LIMITS_SUBSCRIPTIONS"
POLICY = "CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path/"home"))
    for key in list(__import__("os").environ):
        if key.startswith("CHATGLANCE_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("chatglance.codex_resets.time.time", lambda: NOW)


def named_values(user="reader@example.invalid", seed=b"T"):
    return {"CHATGLANCE_LOGIN_USER":user,
            "CHATGLANCE_LOGIN_PASSWORD_HASH":bcrypt.hashpw(b"synthetic-password",bcrypt.gensalt(rounds=4)).decode(),
            "CHATGLANCE_LOGIN_SECRET":base64.b64encode(seed*64).decode(),
            SUBS:json.dumps({"alpha":{"crs_profile":"reader-a","account_id":"account-a","enabled":True},
                             "beta":{"crs_profile":"reader-b","account_id":"account-b","enabled":True},
                             "outside":{"crs_profile":"other-reader","account_id":"outside-id","enabled":True}}),
            POLICY:'{"alpha":{"enabled":true},"beta":{"enabled":true}}',
            "CHATGLANCE_ACCOUNT_LIMITS_CONTROL_PATH":"/_chatglance/reset-policy/"}


def prepare_profile(tmp_path, name="teacher", values=None):
    store = EnvStore(get_paths().envs_dir)
    store.save_profile(ChatGlanceConfig,name,values if values is not None else named_values())
    return store


def spec(**kwargs):
    from chatglance.instances import InstanceSpec
    values=dict(name="teacher",env_profile="teacher",pages=("account-limits",),accounts=("alpha","beta"),
                host="127.0.0.1",port=11080,origin="https://status.example.invalid",read_only=True,interval_seconds=1800)
    values.update(kwargs)
    return InstanceSpec(**values)


def initialized(tmp_path):
    from chatglance.instances import initialize_instance
    prepare_profile(tmp_path)
    root=tmp_path/"teacher-runtime"
    initialize_instance(root,spec(),apply=True)
    return root


def test_instance_public_api_exists():
    assert importlib.util.find_spec("chatglance.instances") is not None


@pytest.mark.parametrize("change",[{"pages":()}, {"pages":("unknown",)}, {"pages":("account-limits","account-limits")},
    {"accounts":()}, {"accounts":("alpha","alpha")}, {"name":"../escape"}, {"env_profile":"default"}, {"read_only":False}])
def test_invalid_instance_contract_is_rejected(change):
    with pytest.raises(ValueError):
        spec(**change)


def test_init_plan_and_apply_only_selected_module(tmp_path):
    from chatglance.instances import initialize_instance, load_instance
    store=prepare_profile(tmp_path)
    store.save_active(ChatGlanceConfig,named_values(user="main@example.invalid",seed=b"M"))
    before=store.load_active(ChatGlanceConfig)
    root=tmp_path/"teacher-runtime"
    result=initialize_instance(root,spec(),apply=False)
    assert result["applied"] is False and not root.exists()
    initialize_instance(root,spec(),apply=True)
    assert load_instance(root).env_profile == "teacher"
    config=yaml.safe_load((root/"config/glance.yml").read_text())
    assert [p["slug"] for p in config["pages"]] == ["account-limits"]
    assert not (root/"data/chatarch-projects.json").exists()
    assert not (root/"data/server-status.json").exists()
    assert not (root/"data/site-services.json").exists()
    assert store.load_active(ChatGlanceConfig)==before


def test_instance_keeps_native_proxied_server_definition(tmp_path):
    root=initialized(tmp_path)
    config=yaml.safe_load((root/"config/glance.yml").read_text())
    assert config["server"]=={"host":"127.0.0.1","port":11080,"proxied":True}


@pytest.mark.parametrize("change", (
    "missing-auth", "optional-auth", "swapped-user", "missing-server", "wrong-server", "unproxied",
    "numeric-proxied", "float-port"))
def test_instance_rejects_changed_native_auth_or_server(tmp_path, change):
    from chatglance.instances import verify_config_pages
    root=initialized(tmp_path)
    path=root/"config/glance.yml"
    config=yaml.safe_load(path.read_text())
    if change=="missing-auth":
        config["auth"]={}
    elif change=="optional-auth":
        config["auth"]["optional"]=True
    elif change=="swapped-user":
        config["auth"]["users"]={"alternate":{"password-hash":"${CHATGLANCE_LOGIN_PASSWORD_HASH}"}}
    elif change=="missing-server":
        config["server"]={}
    elif change=="wrong-server":
        config["server"]["port"]=11081
    elif change=="unproxied":
        config["server"]["proxied"]=False
    elif change=="numeric-proxied":
        config["server"]["proxied"]=1
    else:
        config["server"]["port"]=11080.0
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError):
        verify_config_pages(root)


def test_explicit_named_profile_ignores_poisoned_active_and_process(tmp_path,monkeypatch):
    store=prepare_profile(tmp_path)
    store.save_active(ChatGlanceConfig,{SUBS:'{"private-main":{}}'})
    monkeypatch.setenv(SUBS,"not-json-process-poison")
    settings=collection_settings(env_profile="teacher")
    assert set(json.loads(settings["subscriptions"]))=={"alpha","beta","outside"}


def test_instance_auth_cannot_fall_back_to_main(tmp_path):
    from chatglance.instances import initialize_instance
    from chatglance.managed import runtime_environment
    store=prepare_profile(tmp_path,values={SUBS:named_values()[SUBS]})
    store.save_active(ChatGlanceConfig,named_values(user="main@example.invalid",seed=b"M"))
    root=tmp_path/"teacher-runtime";initialize_instance(root,spec(),apply=True)
    with pytest.raises(ValueError):
        runtime_environment(root,auth=True)


def test_two_runtime_auth_sources_are_independent(tmp_path):
    from chatglance.instances import initialize_instance
    from chatglance.managed import runtime_environment
    store=prepare_profile(tmp_path)
    store.save_active(ChatGlanceConfig,named_values(user="main@example.invalid",seed=b"M"))
    root=tmp_path/"teacher-runtime";initialize_instance(root,spec(),apply=True)
    environment=runtime_environment(root,auth=True)
    expected=store.load_profile(ChatGlanceConfig,"teacher")
    assert environment["CHATGLANCE_LOGIN_USER"]=="reader@example.invalid"
    assert environment["CHATGLANCE_LOGIN_SECRET"]==expected["CHATGLANCE_LOGIN_SECRET"]
    assert environment["CHATGLANCE_LOGIN_SECRET"]!=store.load_active(ChatGlanceConfig)["CHATGLANCE_LOGIN_SECRET"]


def test_read_only_scheduled_refresh_pins_profile_subset_and_never_consumes(tmp_path,monkeypatch):
    root=initialized(tmp_path)
    (root/"bin").mkdir(exist_ok=True);(root/"bin/glance").write_text("synthetic validator")
    calls,clients=install_clients(monkeypatch)
    monkeypatch.setattr(refresh,"validate_glance_config",lambda *a:None)
    result=refresh.refresh_runtime(root,restart=False,scheduled=True,collection=refresh.CollectionOptions(no_public_reset=True))
    assert result["ok"] is True and result["reset_execution"] is False
    assert calls==[("reader-a","account-a"),("reader-b","account-b")]
    assert not any(client.posts for client in clients)
    data=json.loads((root/"data/account-limits.json").read_text())
    assert [row["profile"] for row in data["codex"]]==["alpha","beta"]
    page=yaml.safe_load((root/"data/account-limits-page.yml").read_text())
    assert "/_chatglance/reset-policy/" not in json.dumps(page)


def test_explicit_pages_or_accounts_cannot_widen_instance(tmp_path,monkeypatch):
    root=initialized(tmp_path)
    calls,_=install_clients(monkeypatch)
    for kwargs in [{"pages":["servers"]},{"profiles":["outside"]}]:
        with pytest.raises((ValueError,refresh.RefreshError)):
            refresh.refresh_runtime(root,restart=False,**kwargs)
    assert not calls


def test_instance_serve_rejects_an_added_disabled_page(tmp_path,monkeypatch):
    from chatglance.portable import serve
    root=initialized(tmp_path)
    (root/"bin").mkdir(exist_ok=True);binary=root/"bin/glance";binary.write_text("synthetic");binary.chmod(0o755)
    path=root/"config/glance.yml";config=yaml.safe_load(path.read_text());config["pages"].append({"name":"hidden","slug":"servers","columns":[]});path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError):
        serve(root)


def test_read_only_instance_refuses_controls_listener(tmp_path):
    root=initialized(tmp_path)
    result=CliRunner().invoke(main,["runtime","controls","--runtime-home",str(root)])
    assert result.exit_code!=0


def test_launchd_template_uses_only_owned_native_commands(tmp_path):
    from chatglance.instances import render_launchd_instance
    import plistlib
    root=initialized(tmp_path)
    units=render_launchd_instance(root,python_bin=Path(sys.executable))
    assert len(units)==2
    definitions=[plistlib.loads(value.encode() if isinstance(value,str) else value) for value in units.values()]
    labels={d["Label"] for d in definitions}
    assert "chatarch-glance.teacher.service" in labels
    assert all("--scheduled" not in d["ProgramArguments"] for d in definitions)
    assert all(str(root) in d["ProgramArguments"] for d in definitions)
    assert all("controls" not in d["ProgramArguments"] for d in definitions)


def test_safe_login_provisioning_preserves_active_profile(tmp_path):
    from chatglance.instances import set_instance_login
    root=initialized(tmp_path)
    store=EnvStore(get_paths().envs_dir);store.save_active(ChatGlanceConfig,named_values(user="main@example.invalid",seed=b"M"));before=store.load_active(ChatGlanceConfig)
    result=set_instance_login(root,username="teacher@example.invalid",password="fixture-new-password",apply=True)
    values=store.load_profile(ChatGlanceConfig,"teacher")
    assert bcrypt.checkpw(b"fixture-new-password",values["CHATGLANCE_LOGIN_PASSWORD_HASH"].encode())
    assert len(base64.b64decode(values["CHATGLANCE_LOGIN_SECRET"]))==64
    assert "fixture-new-password" not in json.dumps(result)
    assert store.load_active(ChatGlanceConfig)==before


def test_configure_plan_and_apply_keep_old_config_on_bad_selection(tmp_path):
    from chatglance.instances import configure_instance
    root=initialized(tmp_path)
    before=(root/"config/glance.yml").read_bytes()
    plan=configure_instance(root,spec(accounts=("beta",)),apply=False)
    assert plan["applied"] is False
    assert (root/"config/glance.yml").read_bytes()==before
    with pytest.raises(ValueError):
        configure_instance(root,spec(accounts=("missing",)),apply=True)
    assert (root/"config/glance.yml").read_bytes()==before
    configure_instance(root,spec(accounts=("beta",)),apply=True)
    from chatglance.instances import load_instance
    assert load_instance(root).accounts == ("beta",)


def test_configure_can_disable_and_reenable_modules_from_same_profile(tmp_path, monkeypatch):
    from chatglance.instances import initialize_instance, load_instance, verify_config_pages
    prepare_profile(tmp_path)
    root=tmp_path/"modular-runtime"
    initialize_instance(root,spec(pages=("projects","servers"),accounts=()),apply=True)
    disabled=CliRunner().invoke(main,["runtime","instance","configure","--runtime-home",str(root),
        "--page","projects","--apply"])
    assert disabled.exit_code==0,disabled.output
    assert load_instance(root).pages==("projects",)
    monkeypatch.setattr(refresh,"_collect_page",lambda *a,**kw:pytest.fail("disabled collector called"))
    with pytest.raises(refresh.RefreshError):
        refresh.refresh_runtime(root,pages=["servers"],restart=False)
    before=(root/"config/glance.yml").read_bytes()
    planned=CliRunner().invoke(main,["runtime","instance","configure","--runtime-home",str(root),
        "--page","projects","--page","servers"])
    assert planned.exit_code==0,planned.output
    assert (root/"config/glance.yml").read_bytes()==before
    enabled=CliRunner().invoke(main,["runtime","instance","configure","--runtime-home",str(root),
        "--page","projects","--page","servers","--apply"])
    assert enabled.exit_code==0,enabled.output
    assert load_instance(root).pages==("projects","servers")
    verify_config_pages(root)
    assert [page["slug"] for page in yaml.safe_load((root/"config/glance.yml").read_text())["pages"]]==["projects","servers"]


def test_configure_can_add_enabled_account_from_same_profile(tmp_path):
    from chatglance.instances import initialize_instance, load_instance
    values=named_values()
    registry=json.loads(values[SUBS]);beta=registry.pop("beta")
    values[SUBS]=json.dumps(registry)
    store=prepare_profile(tmp_path,values=values)
    root=tmp_path/"account-runtime"
    initialize_instance(root,spec(accounts=("alpha",)),apply=True)
    registry["beta"]=beta
    values[SUBS]=json.dumps(registry)
    store.save_profile(ChatGlanceConfig,"teacher",values)
    expanded=CliRunner().invoke(main,["runtime","instance","configure","--runtime-home",str(root),
        "--account","alpha","--account","beta","--apply"])
    assert expanded.exit_code==0,expanded.output
    assert load_instance(root).accounts==("alpha","beta")
    with pytest.raises(refresh.RefreshError):
        refresh.refresh_runtime(root,profiles=["outside"],restart=False)


def test_configure_invalid_new_account_fails_before_runtime_writes(tmp_path):
    from chatglance.instances import configure_instance
    root=initialized(tmp_path)
    store=EnvStore(get_paths().envs_dir)
    values=store.load_profile(ChatGlanceConfig,"teacher")
    registry=json.loads(values[SUBS]);registry["beta"]["enabled"]=False
    values[SUBS]=json.dumps(registry)
    store.save_profile(ChatGlanceConfig,"teacher",values)
    before=[(root/name).read_bytes() for name in ("private/instance.json","config/glance.yml")]
    for label in ("missing","beta"):
        with pytest.raises(ValueError):
            configure_instance(root,spec(accounts=("alpha",label)),apply=True)
        assert [(root/name).read_bytes() for name in ("private/instance.json","config/glance.yml")]==before
        assert not (root/"logs/refresh-live-pages.lock").exists()


def test_instance_cli_tree_and_dry_run(tmp_path):
    root=tmp_path/"planned-runtime"
    help_result=CliRunner().invoke(main,["runtime","instance","--help"])
    assert help_result.exit_code==0
    assert all(command in help_result.output for command in ("init","show","configure","set-login","render-launchd"))
    result=CliRunner().invoke(main,["runtime","instance","init","--runtime-home",str(root),
        "--name","planned","--env-profile","planned","--page","account-limits",
        "--account","alpha","--host","127.0.0.1","--port","11081",
        "--origin","https://planned.example.invalid"])
    assert result.exit_code==0, result.output
    assert not root.exists()


def test_instance_preflight_rejects_symlink_runtime(tmp_path):
    from chatglance.instances import initialize_instance
    target=tmp_path/"target";target.mkdir()
    link=tmp_path/"linked-runtime";link.symlink_to(target)
    with pytest.raises(ValueError):
        initialize_instance(link,spec(),apply=True)
    assert list(target.iterdir())==[]


def test_login_password_bounds_fail_before_profile_write(tmp_path):
    from chatglance.instances import set_instance_login
    root=initialized(tmp_path)
    store=EnvStore(get_paths().envs_dir)
    before=store.load_profile(ChatGlanceConfig,"teacher")
    for password in ("", "x"*73):
        with pytest.raises(ValueError):
            set_instance_login(root,username="reader@example.invalid",password=password,apply=True)
        assert store.load_profile(ChatGlanceConfig,"teacher")==before


def test_two_instances_pin_different_profiles_and_accounts(tmp_path, monkeypatch):
    from chatglance.instances import InstanceSpec, initialize_instance
    from chatglance.managed import runtime_environment
    first=named_values(user="first@example.invalid",seed=b"A")
    second=named_values(user="second@example.invalid",seed=b"B")
    second[SUBS]=json.dumps({"gamma":{"crs_profile":"reader-c","account_id":"account-c","enabled":True}})
    prepare_profile(tmp_path,"first",first)
    prepare_profile(tmp_path,"second",second)
    store=EnvStore(get_paths().envs_dir)
    store.save_active(ChatGlanceConfig,named_values(user="poison@example.invalid",seed=b"P"))
    monkeypatch.setenv(SUBS,"not-json-process-poison")
    roots=[]
    for name,account,port in (("first","alpha",11081),("second","gamma",11082)):
        root=tmp_path/name
        initialize_instance(root,InstanceSpec(name=name,env_profile=name,pages=("account-limits",),
            accounts=(account,),host="127.0.0.1",port=port,origin=f"https://{name}.example.invalid"),apply=True)
        (root/"bin/glance").write_text("synthetic validator")
        roots.append(root)
    calls,clients=install_clients(monkeypatch)
    monkeypatch.setattr(refresh,"validate_glance_config",lambda *a:None)
    for root in roots:
        result=refresh.refresh_runtime(root,restart=False,scheduled=True,
            collection=refresh.CollectionOptions(no_public_reset=True))
        assert result["ok"] and not result["reset_execution"]
    assert calls==[("reader-a","account-a"),("reader-c","account-c")]
    assert all(not client.posts for client in clients)
    assert [[row["profile"] for row in json.loads((root/"data/account-limits.json").read_text())["codex"]]
            for root in roots]==[["alpha"],["gamma"]]
    assert [runtime_environment(root,auth=True)["CHATGLANCE_LOGIN_USER"] for root in roots]==[
        "first@example.invalid","second@example.invalid"]
    assert runtime_environment(roots[0],auth=True)["CHATGLANCE_LOGIN_SECRET"]!=runtime_environment(roots[1],auth=True)["CHATGLANCE_LOGIN_SECRET"]


def test_disabled_modules_have_no_collection_calls(tmp_path,monkeypatch):
    root=initialized(tmp_path)
    (root/"bin/glance").write_text("synthetic validator")
    calls,_=install_clients(monkeypatch)
    monkeypatch.setattr(refresh,"validate_glance_config",lambda *a:None)
    for path in ("chatglance.project_inventory.refresh_project_inventory",
                 "chatglance.servers.collect_server_status","chatglance.sites.load_sites_inventory"):
        monkeypatch.setattr(path,lambda *a,**kw:pytest.fail("disabled module collected"))
    refresh.refresh_runtime(root,restart=False,collection=refresh.CollectionOptions(no_public_reset=True))
    assert len(calls)==2


def test_direct_controls_and_maintenance_reject_read_only_instance(tmp_path):
    from chatglance.reset_control import ControlApp, ControlError
    from chatglance.page_control import PageControlApp, PageControlError
    from chatglance.runtime import maintain_config
    root=initialized(tmp_path)
    with pytest.raises(ControlError):
        ControlApp(runtime_home=root,public_origin="https://status.example.invalid",authenticate=lambda _:True)
    with pytest.raises(PageControlError):
        PageControlApp(root,"https://status.example.invalid")
    assert not (root/"private/page-refresh.json").exists()
    with pytest.raises(ValueError):
        maintain_config(config_path=root/"config/glance.yml",data_path=root/"data/chatarch-projects.json")


def test_missing_named_profile_cannot_use_active_profile(tmp_path):
    from chatglance.instances import initialize_instance
    store=EnvStore(get_paths().envs_dir)
    store.save_active(ChatGlanceConfig,named_values())
    root=tmp_path/"missing-runtime"
    with pytest.raises(ValueError):
        initialize_instance(root,spec(),apply=True)
    assert not root.exists()


def test_owned_launchd_reload_rejects_main_and_wrong_interpreter(tmp_path,monkeypatch):
    import plistlib
    import subprocess
    from chatglance import runtime
    from chatglance.instances import render_launchd_instance
    root=initialized(tmp_path)
    agents=tmp_path/"Library/LaunchAgents";agents.mkdir(parents=True)
    units=render_launchd_instance(root,python_bin=Path(sys.executable))
    web=agents/"chatarch-glance.teacher.service.plist"
    web.write_bytes(units[web.name])
    monkeypatch.setattr(sys,"platform","darwin")
    monkeypatch.setattr(runtime.Path,"home",lambda:tmp_path)
    calls=[]
    monkeypatch.setattr(runtime.subprocess,"run",lambda args,**kw:calls.append(args))
    with pytest.raises(ValueError):
        runtime.restart_user_service("chatarch-glance.service",root)
    assert not calls
    definition=plistlib.loads(web.read_bytes())
    definition["ProgramArguments"][0]="/bin/echo"
    web.write_bytes(plistlib.dumps(definition))
    with pytest.raises(ValueError):
        runtime.restart_user_service("chatarch-glance.teacher.service",root)
    assert not calls


def test_owned_launchd_reload_uses_exact_instance_label(tmp_path,monkeypatch):
    from chatglance import runtime
    from chatglance.instances import render_launchd_instance
    import subprocess
    root=initialized(tmp_path)
    agents=tmp_path/"Library/LaunchAgents";agents.mkdir(parents=True)
    units=render_launchd_instance(root,python_bin=Path(sys.executable))
    plist=agents/"chatarch-glance.teacher.service.plist";plist.write_bytes(units[plist.name])
    monkeypatch.setattr(sys,"platform","darwin")
    monkeypatch.setattr(runtime.Path,"home",lambda:tmp_path)
    monkeypatch.setattr(runtime,"_web_ready",lambda host,port:(host,port)==("127.0.0.1",11080))
    states=iter(("state = running\n pid = 123\n","state = running\n pid = 456\n","state = running\n pid = 456\n"))
    calls=[]
    def command(args,**kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args,0,stdout=next(states) if args[1]=="print" else "")
    monkeypatch.setattr(runtime.subprocess,"run",command)
    runtime.restart_user_service("chatarch-glance.teacher.service",root)
    assert [call[1] for call in calls]==["print","bootout","bootstrap","print","print"]
    assert all("chatarch-glance.service" not in call for call in calls)


def test_disabled_tracking_does_not_revive_cached_accounts(tmp_path,monkeypatch):
    root=initialized(tmp_path)
    old={"codex":[{"profile":"alpha"},{"profile":"beta"}]}
    snapshot=root/"data/account-limits.json";snapshot.write_text(json.dumps(old))
    store=EnvStore(get_paths().envs_dir)
    values=store.load_profile(ChatGlanceConfig,"teacher")
    store.save_profile(ChatGlanceConfig,"teacher",{**values,SUBS:"{}"})
    calls,_=install_clients(monkeypatch)
    with pytest.raises(ValueError):
        refresh.refresh_runtime(root,restart=False)
    assert not calls and json.loads(snapshot.read_text())==old


def test_login_cli_uses_named_env_value_without_echo(tmp_path):
    root=initialized(tmp_path)
    password="synthetic-hidden-password"
    result=CliRunner().invoke(main,["runtime","instance","set-login","--runtime-home",str(root),
        "--username","reader@example.invalid","--password-env","FIXTURE_PASSWORD","--apply"],
        env={"FIXTURE_PASSWORD":password})
    assert result.exit_code==0,result.output
    assert password not in result.output
    values=EnvStore(get_paths().envs_dir).load_profile(ChatGlanceConfig,"teacher")
    assert bcrypt.checkpw(password.encode(),values["CHATGLANCE_LOGIN_PASSWORD_HASH"].encode())


def test_configure_rolls_back_on_second_replace_failure(tmp_path,monkeypatch):
    from chatglance import instances
    root=initialized(tmp_path)
    config=root/"config/glance.yml";manifest=root/"private/instance.json"
    before=(config.read_bytes(),manifest.read_bytes())
    replace=instances.os.replace
    count=0
    def fail_second(source,target):
        nonlocal count
        count+=1
        if count==2:
            raise OSError("synthetic publication failure")
        return replace(source,target)
    monkeypatch.setattr(instances.os,"replace",fail_second)
    with pytest.raises(OSError):
        instances.configure_instance(root,spec(accounts=("beta",)),apply=True)
    assert (config.read_bytes(),manifest.read_bytes())==before


def test_instance_binds_provider_home_across_process_environment(tmp_path,monkeypatch):
    from chatglance.managed import runtime_environment
    root=initialized(tmp_path)
    original=str(tmp_path/"home")
    monkeypatch.setenv("CHATARCH_HOME",str(tmp_path/"other-home"))
    monkeypatch.setenv("CHATGLANCE_LOGIN_USER","poison@example.invalid")
    environment=runtime_environment(root,auth=True)
    assert environment["CHATARCH_HOME"]==original
    assert environment["CHATGLANCE_LOGIN_USER"]=="reader@example.invalid"


def test_tampered_snapshot_symlink_rejected_before_provider_reads(tmp_path,monkeypatch):
    root=initialized(tmp_path)
    snapshot=root/"data/account-limits.json"
    snapshot.unlink()
    outside=tmp_path/"outside.json";outside.write_text("{}")
    snapshot.symlink_to(outside)
    monkeypatch.setattr("chatglance.instances.named_profile_values",
                        lambda *a,**kw:pytest.fail("provider read after unsafe path"))
    with pytest.raises(ValueError):
        refresh.refresh_runtime(root,restart=False)


def test_external_instance_inventory_rejected_before_collection(tmp_path):
    root=initialized(tmp_path)
    with pytest.raises(refresh.RefreshError):
        refresh.refresh_runtime(root,restart=False,
            collection=refresh.CollectionOptions(sites_inventory=tmp_path/"external.yml"))


def test_account_scope_removes_old_counts_history_and_resources():
    from chatglance.instances import scope_account_data
    data={"codex":[{"profile":"alpha","reset_history":[{"profile":"outside"},{"profile":"alpha"}]},
                    {"profile":"outside"}],
          "accounts":[{"profile":"outside"}],"rows":[{"profile":"outside"}],
          "counts":{"codex_profiles":2},"refresh_status":{"status":"partial","failed_profiles":["outside"],
              "ok_profiles":["alpha"],"message":"failed_profiles=outside"},
          "resources":[{"kind":"codex","profiles":["alpha","outside"]}],
          "reset_control_path":"/_chatglance/reset-policy/"}
    scoped=scope_account_data(data,("alpha",))
    assert "outside" not in json.dumps(scoped)
    assert scoped["refresh_status"]["profiles_total"]==1
    assert scoped["resources"][0]["profiles"]==["alpha"]


def test_all_enabled_modules_use_their_own_empty_snapshots(tmp_path):
    from chatglance.instances import initialize_instance
    prepare_profile(tmp_path)
    root=tmp_path/"mixed-runtime"
    selected=("projects","servers","sites","account-limits")
    initialize_instance(root,spec(pages=selected),apply=True)
    config=yaml.safe_load((root/"config/glance.yml").read_text())
    assert [page["slug"] for page in config["pages"]]==list(selected)
    assert not (root/"config/server-inventory.yml").exists()
    assert not (root/"config/site-services.yml").exists()
    assert all((root/"data"/name).is_file() for name in (
        "chatarch-projects.json","server-status.json","site-services.json","account-limits.json"))


def test_go_validation_bridge_uses_only_bound_named_login(tmp_path,monkeypatch):
    from chatglance import runtime
    root=initialized(tmp_path)
    store=EnvStore(get_paths().envs_dir)
    store.save_active(ChatGlanceConfig,named_values(user="main@example.invalid",seed=b"M"))
    monkeypatch.setenv("CHATGLANCE_LOGIN_USER","process@example.invalid")
    captured=[]
    monkeypatch.setattr(runtime.subprocess,"run",lambda args,**kwargs:captured.append(kwargs["env"]))
    runtime.validate_glance_config(root/"bin/glance",root/"config/glance.yml")
    assert captured[0]["CHATGLANCE_LOGIN_USER"]=="reader@example.invalid"
    assert captured[0]["CHATGLANCE_LOGIN_SECRET"]!=store.load_active(ChatGlanceConfig)["CHATGLANCE_LOGIN_SECRET"]


def test_two_instances_can_serve_same_installed_go_binary(tmp_path,monkeypatch):
    from chatglance.instances import initialize_instance
    from chatglance.portable import serve
    prepare_profile(tmp_path)
    binary=tmp_path/"shared-glance";binary.write_text("synthetic executable");binary.chmod(0o755)
    roots=[]
    for name,port in (("reader_one",11081),("reader_two",11082)):
        root=tmp_path/name
        initialize_instance(root,spec(name=name,glance_bin=str(binary),port=port),apply=True)
        roots.append(root)
    commands=[]
    monkeypatch.setattr("chatglance.portable.os.execve",lambda path,args,env:commands.append((path,args,env)))
    for root in roots:
        serve(root)
    assert [item[0] for item in commands]==[str(binary),str(binary)]
    assert [item[2]["CHATGLANCE_WEB_PORT"] for item in commands]==["11081","11082"]


def test_missing_instance_manifest_cannot_fall_back_to_main_login(tmp_path):
    from chatglance.managed import runtime_environment
    root=initialized(tmp_path)
    store=EnvStore(get_paths().envs_dir)
    store.save_active(ChatGlanceConfig,named_values(user="main@example.invalid",seed=b"M"))
    (root/"private/instance.json").unlink()
    with pytest.raises(ValueError):
        runtime_environment(root,auth=True)


def test_instance_history_policy_uses_bound_named_profile(tmp_path):
    from chatglance.refresh_history import prune_refresh_history
    root=initialized(tmp_path)
    store=EnvStore(get_paths().envs_dir)
    named=store.load_profile(ChatGlanceConfig,"teacher")
    named["CHATGLANCE_REFRESH_HISTORY_RETENTION_DAYS"]="90"
    store.save_profile(ChatGlanceConfig,"teacher",named)
    store.save_active(ChatGlanceConfig,{"CHATGLANCE_REFRESH_HISTORY_RETENTION_DAYS":"1"})
    plan=prune_refresh_history(root,apply=False)
    assert plan["retention_days"]==90


def test_linux_instance_reload_cannot_target_main_service(tmp_path,monkeypatch):
    from chatglance import runtime
    root=initialized(tmp_path)
    monkeypatch.setattr(sys,"platform","linux")
    calls=[]
    monkeypatch.setattr(runtime.subprocess,"run",lambda args,**kw:calls.append(args))
    with pytest.raises(ValueError):
        runtime.restart_user_service("chatarch-glance.service",root)
    assert calls==[]


def test_project_instance_never_uses_main_or_process_github_token(tmp_path,monkeypatch):
    from chatglance import project_inventory
    from chatglance.instances import initialize_instance,load_instance
    values=named_values()
    values["CHATGLANCE_PROJECTS_OWNER"]="ExampleOrg"
    values["CHATGLANCE_GITHUB_TOKEN"]="named-synthetic-token"
    prepare_profile(tmp_path,values=values)
    store=EnvStore(get_paths().envs_dir)
    store.save_active(ChatGlanceConfig,{"CHATGLANCE_GITHUB_TOKEN":"main-synthetic-token"})
    monkeypatch.setenv("CHATGLANCE_GITHUB_TOKEN","process-synthetic-token")
    root=tmp_path/"project-runtime"
    initialize_instance(root,spec(pages=("projects",),accounts=()),apply=True)
    calls=[]
    monkeypatch.setattr(project_inventory,"resolve_token",lambda *a,**kw:pytest.fail("legacy token resolver used"))
    monkeypatch.setattr(project_inventory,"run_chatgh_repo_list",lambda **kw:calls.append(kw) or [])
    monkeypatch.setattr(project_inventory,"make_github_fetcher",lambda **kw:calls.append(kw) or (lambda *a:None))
    stage=tmp_path/"stage";stage.mkdir()
    refresh._collect_page("projects",root,stage,profiles=None,actual_cli_tree=False,
        allow_offline_regression=True,instance=load_instance(root))
    assert calls[0]["token"]=="named-synthetic-token"
    assert calls[1]["token"]=="named-synthetic-token"


def test_project_instance_missing_named_token_fails_before_chatgh(tmp_path,monkeypatch):
    from chatglance import project_inventory
    from chatglance.instances import initialize_instance,load_instance
    values=named_values();values["CHATGLANCE_PROJECTS_OWNER"]="ExampleOrg"
    prepare_profile(tmp_path,values=values)
    root=tmp_path/"project-runtime"
    initialize_instance(root,spec(pages=("projects",),accounts=()),apply=True)
    monkeypatch.setattr(project_inventory,"run_chatgh_repo_list",lambda **kw:pytest.fail("provider read without named token"))
    stage=tmp_path/"stage";stage.mkdir()
    with pytest.raises(ValueError):
        refresh._collect_page("projects",root,stage,profiles=None,actual_cli_tree=False,
            allow_offline_regression=True,instance=load_instance(root))
