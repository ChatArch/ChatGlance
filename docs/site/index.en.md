# ChatGlance: start with your task

ChatGlance **generates configuration and supports operations** for Glance dashboards; it is not a web server. It produces project, server, website-service, and account pages for an existing Glance instance. Choose your task rather than reading a monolithic CLI tree:

<div class="grid cards" markdown>

-   :material-account-key-outline: **One URL, guest and signed-in views**

    ---

    [Projects and access](projects.md) explains `public: true`, `authenticated-columns`, and the permission boundary at the same `/项目` path. A candidate config does **not** deploy the site.

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
    Official Glance v0.8.5 **does not** implement the `public` pages and server-side `authenticated-columns` selection described here. Use the Linux amd64 binary from [chatarch-v0.1.0](https://github.com/ChatArch/glance/releases/tag/chatarch-v0.1.0) and verify its `SHA256SUMS`. Installing the Python package does not replace a running Glance binary; validate configuration, guest access, login and logout before cutover.

Choose a workflow in [Quickstart](quickstart.md); deployment and rollback boundaries are covered in [Refresh and operations](operations.md).
