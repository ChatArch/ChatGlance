# CLI reference by side effect

These nodes match the registered `chatglance --tree-brief`. For exact arguments, run `chatglance --tree` or `chatglance <group> <command> --help` on the installed version. Do not conflate reads, candidate writes, and runtime mutations.

## Access and page generation

```text
chatglance
├── access
│   ├── render-public
│   └── render-single-origin-optional-login
├── projects
│   ├── collect
│   ├── render-page
│   └── update-config
├── sites
│   ├── collect
│   ├── export-covers
│   ├── render-page
│   └── update-config
└── servers
    ├── candidates
    ├── collect
    ├── render-page
    ├── update-config
    └── validate-refresh
```

`access render-single-origin-optional-login` writes a **private** single-origin candidate to an explicit path. `access render-public` remains a detached public **offline** config/inventory candidate, not a recommended second-site deployment. `projects collect` gathers metadata, `render-page` creates a page fragment, and `update-config` writes a config copy. Server and site collection uses explicit inventories; never place the full project inventory in anonymous assets.

## Refresh and runtime

```text
chatglance
├── refresh
├── runtime
│   ├── controls
│   ├── adopt
│   ├── check
│   ├── history
│   │   ├── list
│   │   ├── prune
│   │   └── show
│   ├── init
│   ├── install
│   ├── import-env
│   ├── install-binary
│   ├── install-systemd
│   ├── maintain
│   ├── maintain-managed
│   ├── paths
│   ├── render-portable
│   ├── render-systemd
│   ├── refresh-managed
│   ├── restart
│   ├── rollback
│   ├── serve
│   ├── start
│   ├── status
│   ├── stop
│   └── update
├── home
│   └── remove-widget
└── disks
    └── root-only
```

`refresh` updates configured pages from existing runtime inventories; manual mode never redeems reset cards. `runtime history list/show` are read-only, while `prune` previews unless `--apply` explicitly removes confirmed-owned history. `runtime init` creates loopback configuration and empty snapshots only; `install-binary` requires a local archive and SHA256. `render-portable` prints or writes review units without registering them; `serve` and `controls` require explicit execution. `runtime maintain` may rewrite runtime config; legacy `install-systemd` and `start` change user-level units and require separate review. See [Refresh and operations](operations.md).

## Account limits and reset controls

Managed `install`, `adopt`, `update`, `rollback`, `stop` and `restart` default to dry-run; `--apply`/`--yes` authorizes writes/actions. `start`/`status` select managed behavior with `--runtime-home`, preserving legacy behavior otherwise. `check` reports validated binary/config ownership; `refresh-managed` and `maintain-managed` are real installed native unit entrypoints, not review-only renderers. See [managed deployment](deployment.md) for complete adoption/rollback and private-input contracts.

```text
chatglance
└── account-limits
    ├── collect
    ├── control-serve
    ├── json
    ├── render-page
    └── update-config
```

`collect` handles account usage and the reset calendar. `control-serve` is an existing authenticated local toggle endpoint. Scheduled reset execution requires explicit `refresh --scheduled` and per-account policy; rendering a page does not authorize consumption. Review access controls before using real accounts.
