# Quickstart: validate before deploying

Glance's `glance.yml`, widgets, and HTML/CSS define the site. ChatGlance helps generate pages, validate config, and maintain snapshots. Do not treat these examples as a production deployment script.

## 1. Install in an isolated environment and inspect the CLI

Use `python -m pip install -e .` from a source checkout, or `python -m pip install ChatGlance` after checking the version actually published to PyPI. **The optional-login CLI requires 0.1.18 source or a released artifact containing it**; it is not part of published 0.1.17.

```bash
chatglance --version
chatglance --tree-brief
chatglance access render-single-origin-optional-login --help
```

If you need to create a config, consult the [maintained Glance fork](https://github.com/ChatArch/glance) for supported YAML. Prepare **synthetic** `private.yml` and `inventory.json`. Retain existing auth and server routing in the input; never commit real configuration. Unmodified v0.8.5 cannot validate the optional-login config.

## 2. Generate a single-origin candidate

Use an existing non-symlink private directory. Filenames below are placeholders; this command does not touch a running service:

```bash
chatglance access render-single-origin-optional-login \
  --config private.yml \
  --inventory inventory.json \
  --output candidate.yml
```

Only completion status is printed, never `auth` or private rows. The output must differ from its inputs and is atomically written at `0600`. The original home, `/项目` slug, and all other login-required pages retain their identities. Making home public does not make other pages public.

## 3. Validate, review, then let operators decide on deployment

Use a deliberately selected Glance executable **with** `public` + `authenticated-columns` support:

```bash
glance -config candidate.yml config:validate
```

Check that guest columns contain only literal `private: false` repositories, while signed-in columns contain all rows with Public/Private/Unknown labels. Operators must separately verify sessions, direct private APIs, logout caches, and desktop/mobile navigation in an isolated environment. A candidate alone is not proof of deployment. See [Projects and access](projects.md) and [Refresh and operations](operations.md).
