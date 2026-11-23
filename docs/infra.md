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
      server_id: "datacenter-primary-01"
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

`alias` selects existing SSH configuration and keys. `server_id` is optional;
when absent, last-good derives a stable SHA-256 ID from alias plus the reviewed
`hostname`, `port`, and `user` connection fence (explicit values override the
SSH selection). An explicit ID remains fenced by all connection fields. Review
membership explicitly; do not include every historical SSH alias automatically.
An unresolvable identity is collected without last-good reuse. The template
`examples/server-inventory.example.yml` documents the same structure.

## Refresh through the installed CLI

```bash
chatglance refresh servers \
  --runtime-home "$HOME/.chatarch/glance" \
  --server-inventory "$HOME/.chatarch/glance/config/server-inventory.yml" \
  --json-output
```

The command shares the runtime lock, collects a candidate snapshot, renders the page, validates the complete candidate with the configured Glance binary, backs up replaced artifacts and publishes transactionally. It restarts the configured Glance service at most once if content changed. Use `--no-restart` when a supervisor owns the separate apply step.

Manual and scheduled refreshes publish the truthful current offline status by
default. If the identity fence matches, the same native card retains the last
successful CPU, memory, GPU, disk/device and system facts, labels them as
historical, and shows both last success and this attempt. A new or changed
identity says that no historical data is available. Use
`--no-allow-offline-regression` only when an operator intentionally wants the
legacy gate that keeps the whole prior server artifact. A removed inventory
member is a membership change and is not re-added from cache.

## Account-level shared traffic (optional)

Install `ChatGlance[aliyun]` into the same Python environment that runs the
main Glance service. The extra provides the Aliyun OpenAPI client and ChatTool's
registered `Aliyun` ChatEnv schema. Keep the AccessKey only in that host's
`~/.chatarch/envs/Aliyun/<profile>.env`, created/maintained through ChatEnv;
never put it in a command, inventory, log, Git checkout or another host. Place a
reviewed copy of `examples/resource-subscriptions.example.yml` at the main
runtime's `config/resource-subscriptions.yml`, replacing only its nonsecret
profile label. Independent instances do not inherit this source.

```bash
chatglance refresh account-limits --runtime-home "$HOME/.chatarch/glance" --no-public-reset --no-restart --json-output
```

This native installed CLI is the reusable collector, renderer, validator and
publisher; a task-local probe is not a deployment script. Manual mode reads
only and does not execute account reset policies. The existing web service
reloads the changed Glance YAML; check the refresh journal's `published`
field and `data/account-limits.json` resource status/`last_successful_at`, not
just CLI exit zero. A partial exit can reflect a separate account failure even
when the cloud card is fresh; when `permission_denied` or `invalid_data` is
reported, do not manufacture zero traffic. The resource card displays one
progress bar per pack with remaining balance and notes exhausted packs
separately. For the official resource-package API, a nonzero unit mismatch is
rejected; `0 Byte` for an exhausted GB pack is an exact zero and safe to show
as exhausted. The BSS read permission is `bss:DescribeInstances` on `*`.

## Scheduled execution

Point the existing user timer at the installed command, not `scripts/refresh-server-status.sh` or a source checkout:

```ini
[Service]
Type=oneshot
ExecStart=%h/.chatarch/venv/bin/chatglance refresh servers --scheduled --runtime-home %h/.chatarch/glance --json-output
```

Preserve the established timer cadence. For a complete site use `chatglance refresh --scheduled`; without page arguments it selects configured generated pages. Retire old wrapper references after verifying the installed command and service.

## Runtime artifacts and acceptance

Runtime files include `data/server-status.json`, the rendered page YAML,
`private/server-last-good.json`, `private/refresh-history/`,
`config/glance.yml`, staging candidates and backups. They are data, not another
implementation of the refresh pipeline. Credentials and private deployment
values stay outside the repository. The complete identity, legacy-bootstrap,
timestamp, journal and rotation schemas are in
[Refresh history and server last-good state](refresh-history.md).

Verify the CLI exit status and each page's result, not only systemd `active` or exit zero from an older wrapper. Re-read snapshot timestamps, changed/partial status and the real authenticated page. A failed page retains prior display values and must not be described as freshly collected.

The lower-level `servers collect`, `validate-refresh`, `render-page` and `update-config` commands remain available for explicit staged workflows. They are not prerequisites for writing a new orchestration shell script.
