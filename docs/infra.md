# Infra / Server Status Page Configuration

`ChatGlance` treats the Glance Infra page as a reproducible pipeline:

1. **Source code** in this repository defines the renderer and safe config patchers.
2. **Infra inventory config** lists which SSH aliases belong on the page and how they are labelled.
3. **External generated data** is collected as a static JSON snapshot by read-only SSH probes.
4. **Generated Glance YAML** is rendered from the staged JSON and inserted into a candidate `glance.yml`.
5. The candidate config is validated before replacing the live JSON, rendered page YAML, and config together; service-manager actions stay in the outer scheduler/wrapper.

The live Glance auth config, password hashes, cookies, tokens, full runtime backups, and host-specific secrets must stay outside this repository and outside PyPI artifacts.

## What is marked as Infra?

A server appears on the Infra/`服务器` page only when it is selected by the server inventory config or by the safe default candidate filter. For the live ChatArch site, prefer an explicit runtime inventory and keep host membership reviewed; do not treat every historical SSH alias, local-only alias, or temporary public host as a dashboard server.

Recommended explicit config:

```yaml
page:
  name: "服务器"
  slug: "servers"
  widget_title: "服务器状态"

inventory:
  default_candidates: false
  exclude: []
  hosts:
    - alias: "infra-cube-1"
      hostname: "172.23.0.10"
      port: 3322
      user: "zhihong"
      strict_host_key_checking: "accept-new"
      label: "cube-1"
      group: "cube"
      connection_kind: "内网连接"
    - alias: "infra-public-1"
      label: "public-1"
      group: "public"
      connection_kind: "公网连接"

collection:
  timeout: 18
  workers: 8
```

Fields:

- `inventory.hosts[].alias`: SSH config alias on the control machine. This is the stable selector.
- `hostname`, `port`, `user`: optional SSH endpoint overrides. When present, ChatGlance still runs `ssh <alias>` so alias-scoped key settings are reused, but passes `-o HostName=...` / `-o Port=...` / `-o User=...` to avoid stale SSH config or DNS entries.
- `strict_host_key_checking`: optional per-host SSH host-key policy, commonly `accept-new` for non-interactive refreshes after reviewed IP changes.
- `label` / `display_name`: optional page label override.
- `group`: presentation/sorting hint such as `cube`, `public`, or `other`.
- `connection_kind`: optional display override, normally `内网连接` or `公网连接`.
- `inventory.exclude`: aliases to keep out even if `default_candidates: true` would select them.
- `collection.timeout` and `collection.workers`: defaults used by `chatglance servers collect` unless CLI flags override them.

A sanitized template lives at `examples/server-inventory.example.yml`. The real live inventory file should be stored with the runtime config, for example:

```text
~/.chatarch/glance/config/server-inventory.yml
```

## What depends on external generated data?

The following are generated artifacts, not source-of-truth source files:

- `server-status.json`: read-only SSH probe output for the current snapshot; the refresh script stages it as `server-status.json.next` first.
- `server-page.yml`: rendered Glance page object for the Infra/`服务器` page; the refresh script stages it as `server-page.yml.next` first.
- `glance.yml.infra-candidate`: temporary candidate full Glance config after replacing the generated page.
- timestamped backups under the runtime backup directory.

Only the code, templates, and documentation belong in this repository. Runtime data should live under the Glance runtime directory, usually:

```text
~/.chatarch/glance/data/server-status.json
~/.chatarch/glance/data/server-page.yml
~/.chatarch/glance/config/glance.yml
~/.chatarch/glance/config/backups/
```

## How do I refresh the Infra page?

Use the external script template:

```bash
CHATGLANCE_INFRA_CONFIG=~/.chatarch/glance/config/server-inventory.yml \
CHATGLANCE_BIN=~/.chatarch/venv/bin/chatglance \
CHATGLANCE_RUNTIME_HOME=~/.chatarch/glance \
bash scripts/refresh-server-status.sh
```

Equivalent manual commands:

```bash
chatglance servers collect \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml \
  --output ~/.chatarch/glance/data/server-status.json.next

chatglance servers validate-refresh \
  --previous ~/.chatarch/glance/data/server-status.json \
  --next ~/.chatarch/glance/data/server-status.json.next

chatglance servers render-page \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml \
  --data ~/.chatarch/glance/data/server-status.json.next \
  --output ~/.chatarch/glance/data/server-page.yml.next

chatglance servers update-config \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml \
  --data ~/.chatarch/glance/data/server-status.json.next \
  --config ~/.chatarch/glance/config/glance.yml \
  --output ~/.chatarch/glance/config/glance.yml.infra-candidate

~/.chatarch/glance/bin/glance -config ~/.chatarch/glance/config/glance.yml.infra-candidate config:validate
```

If validation passes and the candidate differs from the live config, back up `glance.yml`, `server-status.json`, and `server-page.yml`, then move the staged JSON/page YAML and candidate config into place together. Let the outer scheduler or operator perform the service-manager action when needed:

```bash
mkdir -p ~/.chatarch/glance/config/backups
cp ~/.chatarch/glance/config/glance.yml \
  ~/.chatarch/glance/config/backups/glance.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml
cp ~/.chatarch/glance/data/server-status.json \
  ~/.chatarch/glance/config/backups/server-status.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).json
cp ~/.chatarch/glance/data/server-page.yml \
  ~/.chatarch/glance/config/backups/server-page.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml
mv ~/.chatarch/glance/data/server-status.json.next \
  ~/.chatarch/glance/data/server-status.json
mv ~/.chatarch/glance/data/server-page.yml.next \
  ~/.chatarch/glance/data/server-page.yml
mv ~/.chatarch/glance/config/glance.yml.infra-candidate \
  ~/.chatarch/glance/config/glance.yml
```

The bundled refresh script intentionally does not call the service manager. It prints `changed=true ... service_action=external` when the live config changed, so a cron wrapper or systemd user unit can decide how to apply the service lifecycle action.

The `validate-refresh` gate fails closed by default when a host that is still in
the new inventory would change from `online` to a non-online status. This avoids
publishing stale controller SSH/DNS/key problems as live server outages. Set
`CHATGLANCE_ALLOW_SERVER_OFFLINE_REGRESSION=1` only for an intentional offline
publication. If a host is removed from the runtime inventory, its absence is
treated as an intentional membership change rather than an outage regression.

## Cron or timer usage

The refresh script has no embedded secrets and can be scheduled externally. Example cron entry:

```cron
*/30 * * * * CHATGLANCE_BIN=$HOME/.chatarch/venv/bin/chatglance CHATGLANCE_RUNTIME_HOME=$HOME/.chatarch/glance CHATGLANCE_INFRA_CONFIG=$HOME/.chatarch/glance/config/server-inventory.yml bash /path/to/ChatGlance/scripts/refresh-server-status.sh >> $HOME/.chatarch/glance/logs/server-status-refresh.log 2>&1
```

Use a systemd user timer instead of cron if you need unit logging and status. Keep the script path and runtime paths explicit.

## Probe contract

`chatglance servers collect` is read-only. It connects to each selected SSH alias and collects:

- hostname, SSH user, kernel, collected time, `Last Reboot`, and uptime seconds; collected and reboot timestamps are rendered in Beijing time (`+08:00`);
- IPs and connection/display IP policy;
- CPU, memory, `df`, filtered `lsblk`, GPU information, and safe disk summaries;
- optional cube `getdevices.sh` output only when it can be run without installing packages.

It does not install packages, write remote files, or persist credentials.

## Review checklist before changing Infra config

1. Update the runtime inventory file (`server-inventory.yml`) rather than editing generated JSON by hand.
2. Run `chatglance servers candidates --inventory-config ...` to inspect selected aliases.
3. Run the refresh script once manually and read its `changed=...` output.
4. Confirm `glance config:validate` passes before replacing live config.
5. Confirm public unauthenticated access still redirects to `/login`.
6. Log the refresh in the project `progress.md` when it changes live content.
