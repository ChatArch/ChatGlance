# Native CLI deployment contract

This page describes the portable deployment contract. Concrete hostnames, account identities, credentials, live paths and acceptance records belong in private runtime configuration and workspace reports, not this repository.

## Ownership

- The upstream Glance binary serves the website.
- The installed ChatGlance package collects supported sources, renders generated pages, validates candidate configuration and publishes updates under a shared lock.
- ChatCRS owns Codex credential renewal and direct-to-configured-Base-URL HTTP. ChatGlance calls its Python API rather than parsing or rotating OAuth itself.
- User-level service units are thin launchers. ChatEnv profiles, reviewed inventories, generated data and backups remain external state.

## Manual and scheduled commands

```bash
chatglance --version
chatglance --tree
chatglance refresh --runtime-home "$HOME/.chatarch/glance" --json-output
chatglance refresh --scheduled --runtime-home "$HOME/.chatarch/glance" --json-output
```

Manual mode never consumes a reset card. Explicit `--scheduled` mode permits the existing per-account policy to act only after fresh data and all guards pass; it does not introduce a second global account switch. Either mode can request necessary credential renewal through ChatCRS/ChatEnv. Failed renewal is visible failure, not permission to use another proxy or account.

Without page arguments, refresh selects the generated pages configured in the runtime. Explicit page arguments can retain a previously reviewed subset. Keep inventories, profile selection and schedule cadence stable during migration; configure `--server-inventory`, `--sites-inventory`, `--gatus-db` or collector timeouts only when those deployment inputs differ from their defaults.

## User service example

```ini
[Unit]
Description=Refresh configured Glance pages

[Service]
Type=oneshot
EnvironmentFile=-%h/.chatarch/glance/config/refresh.env
UnsetEnvironment=HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
Environment=NO_PROXY=*
Environment=no_proxy=*
ExecStart=%h/.chatarch/venv/bin/chatglance refresh --scheduled --runtime-home %h/.chatarch/glance --json-output
```

The optional environment file contains deployment configuration and approved credential references only. It is not a place for executable business logic. Do not source a `proxy_on` helper or call a checkout-relative refresh script.

Use the existing service/timer names and cadence when replacing an old entry. Back up the unit and wrapper references, install the released package, prove its real CLI tree and non-consuming refresh, switch the unit to the installed command, run the service-manager configuration reload and verify the next actual run. Archive only task-owned retired wrappers after readback confirms that no active unit uses them.

## Publication and verification

The package validates a candidate with the configured Glance executable before replacing generated data and configuration. It preserves unrelated widgets/page ordering, retains failed pages' prior artifacts and performs at most one requested restart. A partial result is not a full refresh success.

Acceptance covers:

1. The installed module and CLI come from the released wheel, not an editable checkout.
2. The service uses the installed CLI directly and still follows the intended timer cadence.
3. Account calls use the configured authentication/backend reverse-proxy URLs with environment/system Proxy ignored.
4. Snapshot timestamps, credential state and card/usage values agree with current source results; cached values are marked as cached.
5. The real website loads and required controls work; service health alone is insufficient.
6. No token, cookie, password, raw account identity or proxy credential enters generated public artifacts.

A rejected refresh token is an authorization checkpoint. Preserve the old state, request renewed authorization through the existing protected flow and do not claim account recovery or card consumption from a package upgrade alone.
