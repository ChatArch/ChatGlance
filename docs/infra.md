# Server inventory and native refresh

ChatGlance owns collection, rendering, candidate validation, backups and publication in the installed package. The server page is generated from a reviewed inventory and read-only SSH probes; it does not require a source checkout or a machine-local business script.

## Inventory

Keep the real inventory beside the runtime configuration, outside Git and distribution artifacts. For example:

```yaml
page:
  name: "服务器"
  slug: "servers"
  widget_title: "服务器状态"
inventory:
  default_candidates: false
  hosts:
    - alias: "infra-primary"
      hostname: "192.0.2.10"
      port: 22
      user: "service-user"
      label: "primary"
      group: "infra"
      connection_kind: "内网连接"
collection:
  timeout: 18
  workers: 4
```

`alias` selects existing SSH configuration and keys. Optional `hostname`, `port`, `user` and `strict_host_key_checking` override only the selected connection. Review membership explicitly; do not include every historical SSH alias automatically. The template `examples/server-inventory.example.yml` documents the same structure.

## Refresh through the installed CLI

```bash
chatglance refresh servers \
  --runtime-home "$HOME/.chatarch/glance" \
  --server-inventory "$HOME/.chatarch/glance/config/server-inventory.yml" \
  --json-output
```

The command shares the runtime lock, collects a candidate snapshot, renders the page, validates the complete candidate with the configured Glance binary, backs up replaced artifacts and publishes transactionally. It restarts the configured Glance service at most once if content changed. Use `--no-restart` when a supervisor owns the separate apply step.

Manual refresh protects previously online servers from unexpected offline regression. Use `--allow-offline-regression` after reviewing an intentional offline transition. Explicit `--scheduled` mode publishes reviewed live outages by default, preserving the existing scheduled behavior; a removed inventory member is a membership change, not an outage.

## Scheduled execution

Point the existing user timer at the installed command, not `scripts/refresh-server-status.sh` or a source checkout:

```ini
[Service]
Type=oneshot
ExecStart=%h/.chatarch/venv/bin/chatglance refresh servers --scheduled --runtime-home %h/.chatarch/glance --json-output
```

Preserve the established timer cadence. For a complete site use `chatglance refresh --scheduled`; without page arguments it selects configured generated pages. Retire old wrapper references after verifying the installed command and service.

## Runtime artifacts and acceptance

Runtime files include `data/server-status.json`, the rendered page YAML, `config/glance.yml`, staging candidates and backups. They are data, not another implementation of the refresh pipeline. Credentials and private deployment values stay outside the repository.

Verify the CLI exit status and each page's result, not only systemd `active` or exit zero from an older wrapper. Re-read snapshot timestamps, changed/partial status and the real authenticated page. A failed page retains prior display values and must not be described as freshly collected.

The lower-level `servers collect`, `validate-refresh`, `render-page` and `update-config` commands remain available for explicit staged workflows. They are not prerequisites for writing a new orchestration shell script.
