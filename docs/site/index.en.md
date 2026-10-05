# ChatGlance: start with your task

ChatGlance **generates configuration and supports operations** for Glance dashboards; it is not a web server. It produces project, server, website-service, and account pages for an existing Glance instance. Choose your task rather than reading a monolithic CLI tree:

<div class="grid cards" markdown>

-   :material-account-key-outline: **One URL, guest and signed-in views**

    ---

    [Projects and access](projects.md) explains `public: true`, `authenticated-columns`, and the permission boundary at the same `/projects` path. A candidate config does **not** deploy the site.

-   :material-rocket-launch-outline: **Build a customizable site**

    ---

    [Quickstart](quickstart.md) begins with a controlled Glance config, synthetic data, and candidate validation; it does not install services or publish files.

-   :material-refresh: **Refresh existing pages**

    ---

    [Refresh and operations](operations.md) separates read-only manual runs, explicit schedules, data rollback, and service lifecycle actions.

-   :material-console: **Find commands and boundaries**

    ---

    The [segmented CLI reference](cli.md) groups access, projects, refresh, and runtime commands. [Architecture and capabilities](architecture.md) describes source-versus-runtime ownership.

</div>

!!! warning "Required Glance capability"
    Official Glance v0.8.5 **does not** implement the `public` pages and server-side `authenticated-columns` selection described here. Use a separately reviewed maintained ChatArch/glance binary with explicit archive SHA256 and exact `--version` (0.2.0 preferred; compatible 0.1.0 when no new Go feature is needed). Do not assume a release checksum file exists. Installing Python does not replace a running server; validate configuration, guest access, login and logout before cutover.

Choose a workflow in [Quickstart](quickstart.md); deployment and rollback boundaries are covered in [Refresh and operations](operations.md).
