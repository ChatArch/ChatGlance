# Projects and single-origin optional login

The full project inventory is **private server-side input**. Only source rows whose `private` field is literally boolean `false` may appear to guests. `true`, absent, and malformed flags must not. Public row URLs still pass an explicit field allowlist and external HTTPS checks. Never rely on CSS/JS to hide private rows.

## Two server-side layouts at the same path

The maintained [ChatArch/glance chatarch-v0.1.0](https://github.com/ChatArch/glance/releases/tag/chatarch-v0.1.0) release supplies `public: true` and `authenticated-columns`: with a valid session, Glance **replaces** ordinary `columns` server-side. Guests read only ordinary columns; other pages remain auth-required by default. Official Glance v0.8.5 lacks this capability. Download the Linux amd64 asset and verify its `SHA256SUMS`; upgrading only the Python package is insufficient.

| Same `/项目` page | Guest `columns` | Valid session `authenticated-columns` |
|---|---|---|
| Rows | Only literal `private: false` | All rows labeled Public/Private/Unknown |
| Details | Allowlisted fields with recomputed counts/categories; no private CLI, Env, or totals | Full details, CLI/Env **structural** descriptions, and visibility labels |
| Route | Existing `项目` name and `/项目` slug | Identical slug; no second public site |

Home similarly uses fixed guest bookmarks and the original private home in authenticated columns. Server, sites, and account pages do not become public merely because home is. Guest navigation excludes them, and Glance must check sessions for direct requests and content APIs. Existing `auth` and trusted `server` routing remain; unsafe shared `document.head`, `head-widgets`, and private assets are not silently copied into the guest shell: candidate generation rejects them. At deployment, verify `no-store` / `Vary: Cookie` caching and logout behavior.

## Candidate and subsequent refresh

```bash
chatglance access render-single-origin-optional-login \
  --config private.yml --inventory inventory.json --output candidate.yml
glance -config candidate.yml config:validate
```

Run this with synthetic data in an isolated directory, using a verified Glance binary with both capabilities. The private candidate is written at `0600`, does not print `auth`, and does not switch services. `projects update-config`, `runtime maintain`, and `refresh projects` use the **trusted** paired page fields to regenerate guest and signed-in columns; they never trust an inventory audience marker. Partial modes fail closed. Existing ordinary private configs retain their default rendering.

Legacy `access render-public` remains an **offline** separate-candidate review tool, not a same-URL optional-login deployment step. Project tables also show recent changes, PR/Issue triage, and category; Python package maturity uses the actual CLI tree of a published version, not entrypoint count alone. Candidate links and ChatEnv field descriptions must never carry credentials. See [operational checks](operations.md).
