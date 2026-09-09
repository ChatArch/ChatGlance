# Website services: default SVG and deployment settings

## No image host by default

Omit `cover_url` to use the built-in SVG data URI. The page YAML contains the image and needs no upload or separate static file server. The SVG destination label comes from the service's actual `public_url`; credentials, query strings and fragments are omitted from that label. Existing titles, descriptions, colors and layout are preserved.

An explicit per-service `cover_url` still selects a custom external image. To return an existing site to default SVG covers, remove `cover_url` from its runtime inventory and collect/render again. Editing generated output alone is not durable. `sites export-covers` exports SVG files, not a whole-site backup.

## Deployment settings

Keep real deployment values in runtime inventory or the existing ChatEnv `ChatGlance` active profile, never in Python defaults or committed configuration.

| ENV | Inventory `page` field | Purpose |
|---|---|---|
| `CHATGLANCE_SITES_PUBLIC_DOMAIN` | `public_domain` | Public DNS suffix for `https://<name>.<suffix>/` |
| `CHATGLANCE_SITES_LOCAL_DOMAIN` | `local_domain` | Optional internal DNS suffix for probes only |
| `CHATGLANCE_SITES_UPTIME_BASE_URL` | `uptime_base_url` | Optional Uptime HTTP(S) base, including a path prefix if needed |

Precedence: **explicit service URL/host > inventory page defaults > process ENV > ChatEnv active profile**. There is no built-in production domain. An explicit empty page value clears the corresponding ENV default.

- Missing both `public_url` and the public suffix is a collection error, not an implicit production destination.
- Empty internal suffix means no generated `local_host`.
- Empty Uptime base means no generated monitoring link.
- DNS suffixes cannot include a scheme, port or path. Use per-service `public_url` for nonstandard destinations.
- Uptime bases cannot contain credentials, query strings or fragments.
- `chatenv test -t chatglance -I` validates configured defaults without network requests.

Reserved example values:

```bash
export CHATGLANCE_SITES_PUBLIC_DOMAIN=public.example.org
export CHATGLANCE_SITES_LOCAL_DOMAIN=internal.example.org
export CHATGLANCE_SITES_UPTIME_BASE_URL=https://status.example.org/
```

The same keys can be stored through ChatEnv's profile editor in the existing `ChatGlance` active profile. Do not create a parallel profile store.

With ENV-managed defaults, inventory can contain only the reviewed service entries:

```yaml
sites:
  - name: docs
    title: Docs
    description: Project documentation.
    cover_summary: Project documentation
  - name: portal
    title: Portal
    public_url: https://portal.example.org/tools/
    description: A custom domain or path-based destination.
```

`examples/site-services.example.yml` instead demonstrates explicit page defaults. Remove its three page address fields when choosing ENV management; otherwise they intentionally override ENV values.

## Generate and validate

```bash
chatglance sites collect --inventory-config /path/to/site-services.yml --output playground/site-services.json
chatglance sites render-page --data playground/site-services.json --output playground/site-services-page.yml
chatglance sites update-config --data playground/site-services.json --config /path/to/glance.yml --output /path/to/glance.candidate.yml
/path/to/glance -config /path/to/glance.candidate.yml config:validate
```

Pass `--gatus-db /path/to/gatus.db` to collection when monitoring status is required. These operations do not configure Nginx/DNS or copy the websites linked by the cards.

## New-machine migration

Git synchronizes renderers, collection code, shared scripts and examples, not the live config, reviewed inventories, data snapshots, account state or installed system services. There is currently no whole-site `export/import` or `backup/restore` command.

For display restoration, prepare a platform-compatible Glance binary and securely transfer the required config/page snapshots. Default SVG covers are self-contained; native RSS/weather widgets still need their data sources.

For continued updates, also prepare ChatGlance dependencies, repository refresh scripts, runtime inventories/overrides, ChatEnv/account authorization, required SSH/network access and target-machine user systemd units. Do not copy a virtualenv or assume old absolute paths are portable.

`runtime render-systemd/install-systemd` covers only its declared Glance and maintenance units, not every custom wrapper, collection timer, reverse proxy or external service. Keep auth, tokens and full live config/backups in controlled storage and authorized transfer, not Git.
