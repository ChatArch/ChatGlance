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

## Manual check and use

After signing in, open the account control popup on the subscription page and choose **检查并用卡** (check and use a credit). Only after explicit confirmation does the server reload that account's current policy, live quota and available cards. It attempts at most one exact card only when the configured threshold and all existing time-window, forecast, identity and idempotency conditions pass. It does not wait for the next scheduled scan or weaken existing safeguards.

Cancelling, viewing, ordinary refreshes and native form submissions without JavaScript never redeem. The action reports success, unmet conditions or an uncertain result with its check time; the checklist above remains explicitly the last scheduled snapshot. Do not repeat an uncertain action before reconciling the ledger and quota. Production acceptance only views or cancels the confirmation; synthetic accounts and cards validate consumption.

## Service boundary

### Force one credit

The account popup's **强制用一张卡** (force one credit) skips automatic enablement, usage thresholds, remaining-time requirements, forecasts and business cooldowns. After separate confirmation, the server consumes at most one exact available credit for that account and reads back credits and usage without changing saved settings. Login, same-origin CSRF and duplicate protection still apply: in-flight or current uncertain operations block another consume, and timeouts never retry automatically. An expired old-window unknown record is archived only under force authorization, not relabelled as unconsumed. The management Key needs consume permission for the selected account.

- `projects update-config` writes an **explicit output path**, not a deployment; a single-origin candidate cannot alias its inputs.
- `runtime maintain` operates on an existing config and can validate, back up, or restart; confirm inputs, permissions, and backups before invoking it on any real runtime.
- `runtime render-systemd` shows templates; `runtime install-systemd` and `runtime start` change user-level service/timer state. This documentation **does not** start them.
- Server collection reads only explicit SSH aliases. Site cards use a reviewed inventory, not automatic domain discovery. `server-stats` shows only meaningful disk mounts.

## Post-deployment functional and security acceptance

1. At the **same URL**, read guest home and `/projects`; inspect navigation, content APIs, HTML/JSON/caches for zero Private identifiers, URLs, counts, or CLI/Env details; verify the exact legacy `/项目` redirect.
2. Sign in with an existing Glance account and inspect all Public/Private/Unknown rows at the same path. Direct visits to private pages and content APIs must be server-protected.
3. Log out, reload, navigate back, and fetch again; private responses must not be recoverable from caches. Test mobile and desktop navigation manually.
4. Identify the actual Glance executable with both `public` and `authenticated-columns`, and retain pre-upgrade config and rollback options. **Do not** mistake a static docs build for this evidence.

Docs deployment uses [GitHub Actions](https://github.com/ChatArch/ChatGlance/actions): PR preview targets `/dev/` and main deploys the root. Both require actual Pages configuration and external readback before anyone can claim publication.
