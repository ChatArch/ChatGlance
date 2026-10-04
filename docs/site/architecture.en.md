# Architecture and capability boundaries

ChatGlance is a Python package and CLI. Glance is the Go server that reads YAML and handles authentication, pages, and APIs. There is no separate Python session or second public site.

```text
Reviewed inventory / runtime snapshots
        │  explicit ChatGlance collection, projection, rendering
        ▼
Candidate glance.yml / page fragments ── Glance config:validate ──► operator publication
                                              │
                        Glance's existing auth, routing, cache, server-side columns
```

## Capability map

| Area | ChatGlance owns | Glance / operators own |
|---|---|---|
| Projects | GitHub metadata, public allowlist, category/version, structural CLI/Env descriptions | Session decisions, authenticated columns at the same `/项目` path, private API isolation |
| Servers | Read-only snapshots for explicit aliases, `server-stats` disks | SSH credentials, permissions, deployment and uptime |
| Websites | Reviewed list, SVG covers, optional monitoring status | URL availability, assets and external network access |
| Accounts | Redacted quota/reset calendar, manual toggles and scheduled decisions | Existing authentication, per-account policies and authorized consumption |

## The single-origin dependency is essential

Official Glance v0.8.5 **does not provide** paired `public: true` and `authenticated-columns`. The maintained [ChatArch/glance chatarch-v0.1.0](https://github.com/ChatArch/glance/releases/tag/chatarch-v0.1.0) release includes both capabilities and a Linux amd64 asset. Verify `SHA256SUMS`, run `config:validate`, and check browser/API behavior in both identities before deployment. The Python package and Glance server binary have separate installation and acceptance boundaries.

Private Glance YAML can contain `auth`; the full inventory can contain Private repositories. They belong to server-side runtime input, never source, docs, public assets, errors, or guest responses. Shared head, branding, and assets need separate review. A detached public offline candidate command still exists but cannot substitute same-origin session selection. See [Projects and access](projects.md).

## Docs and releases have separate pipelines

Source tests, installed-wheel CLI checks, strict MkDocs builds, PR `/dev/` previews, and main-root deploys are different evidence. The docs site receives no credentials or personal runtime details. Pages branch configuration, the repository About link, preview comment URL, and external domain reachability must still be checked after publication. Package tagging/PyPI and the Glance binary switch belong to a separate operator process.
