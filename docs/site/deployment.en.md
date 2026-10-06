# Self-contained managed deployment

## Five layers and compatibility

1. Git-tracked source owns public templates, Python APIs and documentation.
2. The installed **ChatGlance 0.2.2** wheel owns all executable business logic. No unit points at a checkout.
3. A separately maintained **ChatArch/glance chatarch-v0.2.1** binary owns web/login/session handling. The maintained 0.1.0 fork is compatible when no new Go feature is needed; unmodified upstream is not an interchangeable login backend.
4. Typed ChatEnv owns credentials; its `glance/` runtime owns private configuration, inventories, generated snapshots and verified binaries.
5. Optional Linux user-systemd units are thin installed-package entrypoints; nginx is separately operator-managed.

The native project overview refresh icon requires `header-controls-url` support from the maintained Go `chatarch-v0.2.1` or newer. Older binaries cannot display this entry. Python and Go versions are independent: deploy the verified Go binary before regenerating pages.

Supported managed deployment: Linux/POSIX, user systemd, an isolated installed Python environment and a reviewed maintained Go binary for the machine's architecture. Rendering/init can be used without systemd. No automatic release, production migration, service activation, SSH discovery or account redemption occurs on installation. This guide describes operator-authorized actions, not a completed production cutover.

## Generic source and runtime tree

```text
repository/
├── src/chatglance/                 # importable logic + thin CLI
│   ├── managed.py / managed_cli.py  # ownership, adoption, lifecycle
│   └── resources/                  # packaged public assets below
├── scripts/                        # legacy thin source conveniences
├── examples/                       # generic public input examples
└── docs/                           # bilingual guidance + tested CLI trees
CHATARCH_HOME/
├── envs/                           # standard private typed provider store
└── glance/
    ├── bin/glance                  # verified maintained executable
    ├── bin/glance.provenance.json   # version + archive/binary/source hashes
    ├── config/                     # login env references, runtime inventories
    ├── data/ / cache/ / logs/       # generated snapshots and shared refresh lock
    ├── scripts/                    # packaged thin convenience wrappers
    └── private/
        ├── managed.json            # owned names, files, cadence and home
        └── managed-backups/        # mode-0700 backups; blobs mode 0600
user-systemd-directory/
├── chatarch-glance.service
├── chatarch-glance-refresh-pages.service / .timer  # selected pages only
├── chatglance-reset-controls.service              # opt-in authenticated controls
└── chatarch-glance-maintenance.service / .timer    # opt-in only
```

The default runtime is `chatenv.get_paths().home_dir/glance`; `CHATARCH_HOME` selects the provider home and `--runtime-home` selects runtime storage. The ownership manifest remembers the effective provider home for every installed entrypoint. Snapshots are runtime data, not source artifacts. Login identifiers, account bindings and machine-specific inventories are private too.

## From scratch: configure, install, check, start

Install the reviewed wheel into an isolated environment; use that environment's CLI/interpreter. These commands are also a minimal from-scratch shell recipe; packaged shell wrappers only delegate to the CLI.

```bash
export CHATARCH_HOME="$PWD/isolated-home"
chatenv status
chatenv init -t chatglance -i
chatenv set -i
chatglance runtime paths
chatglance runtime init --with-auth
chatglance runtime install-binary --archive reviewed.tar.gz --sha256 EXPECTED_SHA256 --binary-version chatarch-v0.2.1+40_LOWERCASE_HEX
chatglance runtime install --page projects --interval 30min
chatglance runtime install --page projects --interval 30min --apply
chatglance runtime check
chatglance runtime status --runtime-home "$CHATARCH_HOME/glance" --live
chatglance runtime start --runtime-home "$CHATARCH_HOME/glance" --apply
```

The SHA/version placeholders must be replaced with **observed, reviewed artifact metadata**, not invented values. No unchecked latest download or assumed checksum file exists. The archive must contain only one regular `glance` member. Its reviewed digest authorizes bounded staged `--version` execution; exact maintained version is required. Provenance records the actual tag, 40-hex source revision and binary/archive digests.

Interactively store `CHATGLANCE_LOGIN_USER`, `CHATGLANCE_LOGIN_SECRET` (canonical base64 of **exactly 64 bytes**) and complete bcrypt `CHATGLANCE_LOGIN_PASSWORD_HASH`; never plaintext passwords or secrets in argv. Use `chatenv list` and `chatenv use -t chatglance PROFILE` for standard profile lifecycle. **Managed login ignores inherited process `CHATGLANCE_LOGIN_*` and indexed `CHATGLANCE_AUTH_*` values**: the selected active EnvStore profile alone supplies login for startup, validation and controls. For non-auth settings, process environment overrides typed values: owner, selected pages, cadence, web/control ports and public origin. Refresh history uses the same typed-provider/process precedence for `CHATGLANCE_REFRESH_HISTORY_RETENTION_DAYS` (default 30) and `CHATGLANCE_REFRESH_HISTORY_MAX_BYTES` (default 268435456), rejecting invalid values; explicit CLI selections override applicable defaults. CRS remains the owner of its consumer key/OAuth/token profiles; GitHub and other providers reuse existing shared Token resolvers, not another credential store.

Without login, omit `--with-auth`; init cannot silently convert an existing unauthenticated config. Starter home is loopback-only and empty inventories make no network calls. Add reviewed page widgets before refreshing. Machine exclusions belong exclusively in private runtime `server-inventory.yml` under `inventory.exclude` / `inventory.excludes`; only universal `local`/`localhost` exclusions are built in. `default_candidates: false` stays off unless explicitly reviewed.

`runtime install` defaults to a mutation-free plan. `--apply`/`--yes` verifies Go config and unit syntax, backs up affected owned files, atomically replaces each file and runs daemon-reload. Enable/start require separate explicit `--enable`/`--start` on an applied install. New units require installed Python paths, never source checkout paths. Unknown files and symlinks are refused; `--adopt-units` authorizes only reviewed selected existing unit replacement. Effective systemd `FragmentPath`, `DropInPaths`, `EnvironmentFiles` and `ExecStart` are checked: selected user-unit `.service.d/*.conf` overlays require explicit `--retire-dropins` after review; the CLI backs them up, retires them and verifies a clean effective command after daemon-reload. Other overlays and unexpected commands fail closed. Unit names reject URI/newline/specifier injection and quoted paths escape spaces/percent signs. Existing unit topology cannot be silently abandoned; stop/review before changing ownership.

## Adopt an existing runtime without secret export

Do not copy production notes into source. Select an existing runtime within the same provider home, back it up privately, and use dry-run counts first:

```bash
chatglance runtime adopt --runtime-home "$CHATARCH_HOME/glance" --public-origin https://example.invalid --control-port 5679
chatglance runtime adopt --runtime-home "$CHATARCH_HOME/glance" --public-origin https://example.invalid --control-port 5679 --apply
chatglance runtime install --runtime-home "$CHATARCH_HOME/glance" --web-unit chatarch-glance.service --refresh-unit chatarch-glance-refresh-pages.service --refresh-timer chatarch-glance-refresh-pages.timer --page servers --page account-limits --page projects --interval 30min --adopt-units
chatglance runtime import-env --runtime-home "$CHATARCH_HOME/glance" --file config/legacy.env --retire
# Only after reviewing source keys and typed-provider conflicts: import-env ... --retire --apply
# Only after inspecting selected user-unit drop-ins: add --retire-dropins; add --apply only after review.
```

Adoption preserves the **exact signing key and every bcrypt hash** so already-logged-in sessions remain valid. It migrates all users into sensitive typed `CHATGLANCE_LOGIN_ACCOUNTS`, indexes safe child env variables, and replaces only auth/port settings with Go `${ENV_NAME}` references after Go validation. Page/widget structure remains intact; generated snapshot bytes are untouched. YAML formatting/comments may be normalized. Conflicting typed values fail unless explicitly authorized with `--replace-provider`; unrelated provider policies remain intact. Changed source/provider inputs abort publication. Dry-run reports only counts/key names. Private backups contain previous secret-bearing inputs: protect them like the provider store, never publish them.

`runtime import-env --file config/NAME.env` (or `private/NAME.env`) reads **only selected runtime-relative, literal env assignments**; it never evaluates shell. Known ChatGlance typed schema keys and legacy `PROFILES` → `CHATGLANCE_ACCOUNT_LIMITS_PROFILES` are imported; `MODELS` and other unknown keys are reported by **name only**, not silently carried into production. Conflicts require `--replace-provider`. `--retire --apply` backs up the selected private file, writes the typed active profile and deletes that source **after typed readback**. Verify policy/profile keys in the provider before retiring legacy EnvironmentFile overlays with `runtime install --retire-dropins --adopt-units --apply`. No selected user-unit drop-in is imported as shell script. The source-backed rollback ID restores provider/source bytes. Never put the private backup into Git.

Use the existing owned service names rather than introducing a second portable web service. Explicit `--scheduled` permits existing per-account policies to execute; first install defaults **off**, and subsequent omitted flags preserve cadence/pages/scheduled settings. Merely selecting `account-limits` does not authorize redemption. Native refresh uses the shared lock, validates/publishes, then restarts only the adopted web service **once and only on change**. No forced `--no-restart`, no independent scheduler, no unconditional second restart. Install/update/maintenance refuse active, activating or reloading collector owners; maintenance is unnecessary unless explicitly enabled.

## Controls and maintenance

Controls require complete login, reviewed HTTPS `CHATGLANCE_PUBLIC_ORIGIN`, a private account-limits page and a loopback control port. After reviewing configuration:

```bash
chatglance runtime install --controls --page account-limits
chatglance runtime install --controls --page account-limits --apply
chatglance runtime controls
# Optional maintenance only: runtime install --maintenance --apply
```

The foreground `controls` command intentionally runs the authenticated server. Managed controls/refresh/validation use the same effective ChatEnv home and no credential-duplicating EnvironmentFile. Review the packaged host-neutral nginx example for same-origin `/_chatglance/reset-policy/`, Glance login routes and legacy `/项目` to `/projects` redirect. Replace `example.invalid`, upstream ports and optional TLS explicitly. ChatGlance never installs/reloads nginx.

## Check, update, rollback and stop

```bash
chatglance runtime check --runtime-home "$CHATARCH_HOME/glance" --live
chatglance runtime restart --runtime-home "$CHATARCH_HOME/glance"
chatglance runtime stop --runtime-home "$CHATARCH_HOME/glance" --apply
chatglance runtime update --runtime-home "$CHATARCH_HOME/glance" --archive reviewed-next.tar.gz --sha256 EXPECTED_SHA256 --binary-version chatarch-v0.2.1+40_LOWERCASE_HEX
chatglance runtime update --runtime-home "$CHATARCH_HOME/glance" --archive reviewed-next.tar.gz --sha256 EXPECTED_SHA256 --binary-version chatarch-v0.2.1+40_LOWERCASE_HEX --apply --restart
chatglance runtime rollback --runtime-home "$CHATARCH_HOME/glance" --backup BACKUP_ID
chatglance runtime rollback --runtime-home "$CHATARCH_HOME/glance" --backup BACKUP_ID --apply
```

Start/stop/restart/update/rollback are dry-run unless applied. Actions constrain targets to owned manifest units. Check **fails on unmanaged runtimes** or mismatched effective fragment/drop-in/environment/command; it distinguishes installed Python code, actual binary version/digest, config validation and optional live unit PIDs. Status prints hashes/counts/presence, never raw systemd environment, login material or account identifiers. Update requires a reviewed local artifact, verifies exact version and candidate config before binary+provenance replacement, and optionally restarts its own web unit. On restart failure it restores old bytes, attempts normal restart of the previously active web and checks state/PID; recovery failure is explicit. Install handles partial enable/start by undoing only newly enabled/started entries, restoring files/reloading and checking formerly active entries. Rollback prechecks every owned target and backup digest; changed/unknown targets fail rather than clobber. Explicit `runtime rollback` restores files/reloads, but does **not** undo enablement/activation or automatically restart an old process; explicitly restart after reviewing rollback.

## Complete packaged public asset inventory

Every row below lives under `src/chatglance/resources/`, is included in wheel/sdist package data, and is tracked with the source commit. `assets.json` is the machine-readable manifest. Generated units contain no secret values; private inputs are read at runtime from typed ChatEnv/inventories.

| Repository resource | Packaged/runtime role | Private inputs |
| --- | --- | --- |
| `glance.yml` | starter `config/glance.yml` | env login refs, reviewed pages/ports |
| `server-inventory.yml` | empty server inventory | explicit SSH aliases/exclusions |
| `site-services.yml` | empty site inventory | operator-reviewed sites |
| `reverse-proxy.example.conf` | reviewed nginx example only | origin/TLS/loopback ports |
| `start.sh` | thin foreground CLI wrapper | effective ChatEnv home |
| `install.sh` | thin init wrapper, not service activation | effective ChatEnv home |
| `refresh.sh` | thin native refresh wrapper | selected runtime pages |
| `web.service` | Go startup via installed env bridge | sensitive typed login |
| `refresh.service` | native owned refresh pipeline | inventories/provider policy |
| `refresh.timer` | selected cadence | reviewed schedule |
| `controls.service` | optional authenticated toggle server | Go login/provider accounts |
| `maintenance.service` | optional native maintenance | runtime config |
| `maintenance.timer` | optional cadence | reviewed schedule |
| `assets.json` | complete asset manifest | none |

Reusable APIs: `chatglance.managed.install_runtime`, `adopt_runtime`, `runtime_status`, `service_action`, `update_binary`, `rollback_runtime`, `refresh_managed`, `maintain_managed`. Existing legacy `render-portable` / `install-systemd` remain compatible, but managed installations use this ownership workflow. [CLI reference](cli.md) and repository `docs/cli-tree.md` are tested against actual `chatglance --tree` / `--tree-brief`; they are the authoritative flags.

Source-only legacy/development conveniences (tracked and included in sdist, **not wheel production entrypoints**):

| Repository path | Source/runtime role | Private inputs |
| --- | --- | --- |
| `scripts/chatglance-from-source` | developer-only checkout runner | local development paths |
| `scripts/collect-codex-account-limits.py` | thin legacy collector entry | existing ChatCRS provider |
| `scripts/refresh-live-pages.sh` | legacy development refresh convenience | selected runtime home |
| `scripts/refresh-manual.sh` | legacy manual refresh convenience | selected runtime home |
| `scripts/refresh-projects-page.sh` | legacy project convenience | runtime projects inventory |
| `scripts/refresh-server-status.sh` | legacy server convenience | runtime SSH inventory |
| `scripts/refresh-sites-page.sh` | legacy sites convenience | runtime site inventory |
| `scripts/refresh-account-limits-page.sh` | legacy account convenience | existing typed provider |
| `examples/server-inventory.example.yml` | generic source-only inventory | real aliases belong in runtime |
| `examples/site-services.example.yml` | generic source-only inventory | real sites belong in runtime |

`assets.json` lists both the 14 wheel resources (including itself) and these ten source-only assets. Installed-package Python modules under `src/chatglance/` contain all production business logic. `controls.service` uses a bounded `TasksMax=128` instead of inheriting a narrow legacy worker limit.
