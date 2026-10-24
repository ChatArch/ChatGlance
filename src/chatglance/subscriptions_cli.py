"""Thin CLI adapters for explicit account tracking, never credential issuance."""
from pathlib import Path
import json
import click

from .subscriptions import change_subscription, list_subscriptions


def register_subscriptions_cli(parent):
    @parent.group("subscriptions")
    @click.option("--env-profile", default=None, help="Named ChatGlance profile; does not activate it.")
    @click.option("--home", type=click.Path(path_type=Path, file_okay=False), default=None, help="Explicit ChatArch home.")
    @click.pass_context
    def subscriptions(ctx, env_profile, home):
        """Manage explicit CRS account tracking; not credential or reset permissions."""
        ctx.ensure_object(dict)
        ctx.obj["subscription_config"] = {"home": home, "env_profile": env_profile}

    def emit(operation, json_output, **kwargs):
        try:
            result = operation(**kwargs)
        except (ValueError, OSError, RuntimeError):
            raise click.ClickException("Subscription operation failed; verify explicit profile, binding and publication lock.") from None
        if json_output:
            click.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
        elif "subscriptions" in result:
            for row in result["subscriptions"]:
                status = "removed" if row.get("removed") else "enabled" if row["enabled"] else "disabled"
                click.echo(f'{row["name"]}\t{row["crs_profile"]}\t{row["account_id"]}\t{status}')
            click.echo(f'count={result["count"]} source={result["source"]}')
        else:
            click.echo(f'{result["action"]} {result["name"]}: {"saved" if result["executed"] else "plan only; use --execute"}')

    @subscriptions.command("list")
    @click.option("--all", "include_removed", is_flag=True, help="Include retained removed identity references.")
    @click.option("--json-output", is_flag=True)
    @click.pass_context
    def list_entries(ctx, include_removed, json_output):
        """List tracked account/profile references without reading credentials."""
        emit(list_subscriptions, json_output, include_removed=include_removed, **ctx.obj["subscription_config"])

    @subscriptions.command("add")
    @click.argument("name")
    @click.option("--crs-profile", required=True, help="Existing CRS profile with its scoped management Key.")
    @click.option("--account-id", required=True, help="Exact CRS account ID; not an OAuth identity.")
    @click.option("--enabled/--disabled", default=True, help="Tracking only; new automatic-use policy stays disabled.")
    @click.option("--execute", is_flag=True, help="Persist the tracking change; otherwise plan only.")
    @click.option("--json-output", is_flag=True)
    @click.pass_context
    def add(ctx, name, crs_profile, account_id, enabled, execute, json_output):
        """Register an account through an existing profile; never rewrite its Key."""
        emit(change_subscription, json_output, action="add", name=name, crs_profile=crs_profile,
             account_id=account_id, enabled=enabled, execute=execute, **ctx.obj["subscription_config"])

    for action, description in (
        ("enable", "Resume tracking without enabling automatic card use."),
        ("disable", "Pause tracking and deny stale account controls."),
        ("remove", "Stop tracking; retain history, policy and the label identity fence."),
    ):
        def register(name, help_text):
            @subscriptions.command(name, help=help_text)
            @click.argument("name")
            @click.option("--execute", is_flag=True, help="Persist the tracking change; otherwise plan only.")
            @click.option("--json-output", is_flag=True)
            @click.pass_context
            def mutate(ctx, name, execute, json_output):
                emit(change_subscription, json_output, action=action_name, name=name,
                     execute=execute, **ctx.obj["subscription_config"])
            action_name = name
        register(action, description)
