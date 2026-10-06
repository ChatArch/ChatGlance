# Refresh history and server last-good state

ChatGlance keeps current connectivity, the last successful server observation,
and refresh-run history as separate runtime facts. All files below live under
the selected Glance runtime; none belongs in source control or a public asset
directory.

## Server identity and current snapshot

Last-good retention requires a reviewed connection identity (`hostname`,
`user`, and `port`, either explicit in the inventory or resolved read-only from
the selected SSH alias). `server_id` is optional: when absent, ChatGlance
derives a deterministic SHA-256 ID from the alias and reviewed target/user/port.
An explicit ID remains supported, but it does not relax the target/user/port
fence. A changed target, user, port, alias, or explicit server ID cannot reuse
the old cache while offline. An unresolvable host fails closed without
disabling independently reviewable hosts.

```yaml
inventory:
  hosts:
    - alias: infra-primary
      server_id: datacenter-primary-01
      hostname: 192.0.2.10
      port: 22
      user: service-user
```

`data/server-status.json` remains the current inventory membership and current
connection result. Each row uses:

- `status`: current `online`, `unreachable`, or `error`; cached data never turns
  an offline row online.
- `last_attempt_at`: this run's connection attempt time.
- `last_observed_at` / `last_success_at`: the successful observation backing
  the hardware fields.
- `data_state`: `fresh`, `last-good`, or `unavailable`.
- Existing real fields (`cpu`, `memory`, `gpus`, `disks`, `devices`,
  `getdevices`, `kernel`, `last_reboot`, `uptime_seconds`) are retained from the
  fenced last-good row while offline. No synthetic `mounts` or `system` fields
  are introduced.

The private `private/server-last-good.json` schema is:

```json
{
  "schema_version": 1,
  "updated_at": "2026-10-06T08:00:00+00:00",
  "servers": {
    "datacenter-primary-01": {
      "identity": {
        "server_id": "datacenter-primary-01",
        "alias": "infra-primary",
        "target": "192.0.2.10",
        "port": "22",
        "user": "service-user"
      },
      "last_success_at": "2026-10-06T07:59:58+00:00",
      "run_id": "20261006T080000000000Z-example",
      "data": {"alias": "infra-primary", "cpu": {}, "memory": {}, "gpus": [], "disks": [], "devices": [], "getdevices": []}
    }
  }
}
```

The real `data` object also contains the validated system facts listed above.
User notes are never copied into last-good or `server-status.json`; they remain
in the existing private notes store and are overlaid only while rendering.
Inventory removal removes the card and the next cache candidate.

Last-good is one payload in the same validated publication transaction as the
current JSON/page/config. Candidate validation or publication rollback cannot
commit an observation that was never published. A restart error occurs after a
successful publication, so the published observation remains truthful.

## Legacy bootstrap

If no valid last-good entry exists and the current row is offline, ChatGlance
checks the existing `data/server-status.json`, then at most 64
`config/backups/refresh-*` directories in reverse name order. A backup is read
only when its regular `manifest.json` maps exactly `data/server-status.json` to
a direct numeric filename. Symlinks, traversal, oversized/malformed snapshots,
future timestamps, failed rows, missing required hardware groups, wrong IP, or
wrong actual remote user are rejected. Remote `hostname` is a system fact and
is not compared with the SSH target. Legacy backups are never deleted.

For a DNS target whose historical endpoint IP cannot otherwise be proved, an
operator may approve the exact old endpoint explicitly:

```yaml
legacy_identities:
  - approved: true
    ip: 192.0.2.10
    port: 22
    user: service-user
```

This is a one-way bootstrap fence, not an alias-only match and not permission
to scan other backup paths.

## Refresh-run journal schema

The package owns only this subtree:

```text
private/refresh-history/
├── active-<run_id>.lock
├── journal.lock
├── latest.json
├── runs/<run_id>.json
└── snapshots/<run_id>.json
```

Directories are mode `0700`, files mode `0600`, and symlink/path traversal is
rejected. `runs` and `latest` use owner marker
`chatglance.refresh-history/v1`, schema version 1, and an allowlist of:

- `run_id`, `source` (`native`, `manual`, `scheduled`, `browser`), requested page keys,
  status and start/finish/elapsed timestamps;
- per-page page/status, allowlisted numeric counts, valid `generated_at`, and a
  fixed `collection_error` category;
- collection/validation/publication/restart phase status, nullable boolean
  changed/published/restarted facts (`null` means an interrupted operation has
  no trustworthy completion receipt), and a basename-only backup ID;
- active-process PID/start identity, a per-run owner lease for the pre-lock
  window, and exact refresh-lock device/inode evidence after acquisition.

The journal never copies exception messages, stdout/stderr, URLs, headers,
Token/Cookie values, config, credentials, account/profile rows, or complete page
snapshots. The optional `snapshots` file is sanitized publication metadata
(page/status/count/time facts), not a raw page payload and not a historical
server-hardware metrics database. Current identity-fenced hardware facts live
only in `private/server-last-good.json`. A previous `running` record becomes interrupted on the next writer
only when its PID/start identity is gone or its exact refresh lock is no longer
held; elapsed age alone is never evidence. Durable checkpoints preserve page
results and completed phases before validation/publication/restart, and record
known completion immediately afterward. Recovery marks only the in-flight
phase interrupted and later untouched phases not started. `list` and `show` calculate an
`effective_status` without repairing or writing records.

## Retention, CLI, and APIs

Typed ChatEnv/process settings are non-secret:

| Key | Default | Validation |
|---|---:|---|
| `CHATGLANCE_REFRESH_HISTORY_RETENTION_DAYS` | `30` | integer 1..3650 |
| `CHATGLANCE_REFRESH_HISTORY_MAX_BYTES` | `268435456` (256 MiB) | integer 1 MiB..16 GiB |

Both limits apply: over-age bundles are candidates, then oldest unprotected
bundles are selected until actual aggregate feature-owned run and metadata
snapshot bytes (plus `latest.json`) fit. Owned snapshots are discovered and
counted independently, so an orphan left by interrupted pruning converges on a
later apply; deletion removes a snapshot before its matching run record. The latest
run, active runs, future-dated records, the newest published rollback point,
and run IDs referenced by last-good are protected. Malformed/unowned files and
legacy `config/backups` (including numeric backup payloads) are never counted as
owned history and are never removed. Automatic pruning runs after newly
completed owned records; it does not create an unbounded trash directory.

```bash
chatglance runtime history list --runtime-home "$CHATARCH_HOME/glance"
chatglance runtime history show RUN_ID --runtime-home "$CHATARCH_HOME/glance"
chatglance runtime history prune --runtime-home "$CHATARCH_HOME/glance"
chatglance runtime history prune --runtime-home "$CHATARCH_HOME/glance" --apply
```

`list` and `show` are read-only. `prune` is a preview unless `--apply` is
explicit. Importable APIs are `list_refresh_runs`, `show_refresh_run`, and
`prune_refresh_history` in `chatglance.refresh_history`; server preparation is
`prepare_server_refresh` in `chatglance.server_cache`. The latter returns a
transaction-ready plan and deliberately does not write last-good by itself.
