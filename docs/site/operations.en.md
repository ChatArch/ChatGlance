# Refresh, runtime, and acceptance

**Keep three boundaries distinct:** generating a local candidate, publishing validated snapshots into an existing runtime, and starting or restarting the actual Glance service. The first two do not prove the external site changed.

## Manual reads versus explicit scheduling

```bash
chatglance refresh projects --no-restart
chatglance refresh sites --no-restart
chatglance refresh --json-output --no-restart
```

`refresh` collects and publishes only managed pages already present in the Glance config and reports success/partial failure per page. It validates a candidate with the selected Glance binary's `config:validate` before backup and replacement; failed pages keep old files, with a shared nonblocking lock. `--no-restart` leaves the service running as-is. These commands are **illustrative**: missing runtime, credentials, or validator cause failure; they do not set up an environment for you.

Manual calls without `--scheduled` never redeem reset cards; account pages only display snapshots. Existing scheduling must use explicit `--scheduled` with per-account policy, not infer authority from a rendered toggle. When refreshing projects in optional-login mode, guest columns are rebuilt from the Public allowlist and authenticated columns retain full rows. A broken layout is rejected rather than overwritten with private guest content.

## Service boundary

- `projects update-config` writes an **explicit output path**, not a deployment; a single-origin candidate cannot alias its inputs.
- `runtime maintain` operates on an existing config and can validate, back up, or restart; confirm inputs, permissions, and backups before invoking it on any real runtime.
- `runtime render-systemd` shows templates; `runtime install-systemd` and `runtime start` change user-level service/timer state. This documentation **does not** start them.
- Server collection reads only explicit SSH aliases. Site cards use a reviewed inventory, not automatic domain discovery. `server-stats` shows only meaningful disk mounts.

## Post-deployment functional and security acceptance

1. At the **same URL**, read guest home and `/项目`; inspect navigation, content APIs, HTML/JSON/caches for zero Private identifiers, URLs, counts, or CLI/Env details.
2. Sign in with an existing Glance account and inspect all Public/Private/Unknown rows at the same path. Direct visits to private pages and content APIs must be server-protected.
3. Log out, reload, navigate back, and fetch again; private responses must not be recoverable from caches. Test mobile and desktop navigation manually.
4. Identify the actual Glance executable with both `public` and `authenticated-columns`, and retain pre-upgrade config and rollback options. **Do not** mistake a static docs build for this evidence.

Docs deployment uses [GitHub Actions](https://github.com/ChatArch/ChatGlance/actions): PR preview targets `/dev/` and main deploys the root. Both require actual Pages configuration and external readback before anyone can claim publication.
