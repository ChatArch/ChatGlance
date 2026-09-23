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
│   ├── install-systemd
│   ├── maintain
│   ├── render-systemd
│   ├── start
│   └── status
├── home
│   └── remove-widget
└── disks
    └── root-only
```

`refresh` updates configured pages from existing runtime inventories; manual mode never redeems reset cards. `runtime maintain` may rewrite the designated runtime config; `install-systemd` and `start` change user-level units and require separate review. `render-systemd` can print templates only. See [Refresh and operations](operations.md).

## Account limits and reset controls

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
