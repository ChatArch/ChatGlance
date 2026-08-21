# CLI 树

下面两棵树都由 ChatStyle 从真实 Click command registry 生成。测试会直接运行 `chatglance --tree` 与 `chatglance --tree-brief` 并比较 fenced blocks，避免文档与真实命令面漂移。

## 完整树

`chatglance --tree` 保留参数与选项签名：

```text
chatglance
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
├── account-limits  # Render the `订阅详情` Glance page.
│   ├── json [--data DATA-PATH] [--output OUTPUT-PATH]  # Write normalized, redacted account/quota JSON.
│   ├── render-page [--data DATA-PATH] [--output OUTPUT-PATH] [--page-name PAGE-NAME] [--page-slug PAGE-SLUG] [--widget-title WIDGET-TITLE]  # Write the `订阅详情` page YAML from account-limits JSON.
│   └── update-config [--data DATA-PATH] [--config CONFIG-PATH] [--output OUTPUT-PATH] [--page-name PAGE-NAME] [--page-slug PAGE-SLUG] [--widget-title WIDGET-TITLE]  # Write a config copy with the generated account-limits page replaced.
├── disks  # Patch Glance server-stats disk display.
│   └── root-only [--config CONFIG-PATH] [--output OUTPUT-PATH] [--mountpoint MOUNTPOINT] [--name MOUNT-NAME]  # Write a config copy that hides default snap/loop mountpoints.
├── home  # Patch ChatArch home-page widgets.
│   └── remove-widget [--config CONFIG-PATH] [--output OUTPUT-PATH] [--type WIDGET-TYPES] [--home-page-name HOME-PAGE-NAME]  # Write a config copy with unavailable home-page widgets removed.
├── projects  # Generate Glance project dashboard pages.
│   ├── collect [--owner OWNER] [--repo-list-json REPO-LIST-JSON] [--baseline-data BASELINE-DATA] [--output OUTPUT-PATH] [--chatgh-bin CHATGH-BIN] [--uvx-bin UVX-BIN] [--limit LIMIT] [--workers WORKERS] [--timeout TIMEOUT] [--actual-cli-tree] [--cli-tree-timeout CLI-TREE-TIMEOUT]  # Write refreshed project inventory JSON from read-only GitHub metadata.
│   ├── render-page [--data DATA-PATH] [--output OUTPUT-PATH] [--page-name PAGE-NAME]  # Write the `项目` page YAML from inventory JSON.
│   └── update-config [--data DATA-PATH] [--config CONFIG-PATH] [--output OUTPUT-PATH] [--page-name PAGE-NAME]  # Write a config copy with the generated project page replaced.
├── runtime  # Maintain a durable Glance service runtime.
│   ├── install-systemd [--runtime-home RUNTIME-HOME] [--chatglance-bin CHATGLANCE-BIN] [--output-dir OUTPUT-DIR] [--service-name SERVICE-NAME] [--maintenance-service-name MAINTENANCE-SERVICE-NAME] [--timer-name TIMER-NAME] [--interval INTERVAL] [--verify] [--enable] [--start]  # Install, verify, enable, and optionally start user-level systemd units.
│   ├── maintain [--runtime-home RUNTIME-HOME] [--config CONFIG-PATH] [--data DATA-PATH] [--backup-dir BACKUP-DIR] [--page-name PAGE-NAME] [--validate] [--glance-bin GLANCE-BIN] [--restart-service RESTART-SERVICE]  # Update runtime config atomically and optionally restart a service.
│   ├── render-systemd [--runtime-home RUNTIME-HOME] [--chatglance-bin CHATGLANCE-BIN] [--service-name SERVICE-NAME] [--maintenance-service-name MAINTENANCE-SERVICE-NAME] [--timer-name TIMER-NAME] [--interval INTERVAL] [--output-dir OUTPUT-DIR]  # Print user units or write them to an output directory.
│   ├── start [--service-name SERVICE-NAME] [--timer-name TIMER-NAME] [--timer]  # Start the current Glance page through systemd user units.
│   └── status [--service-name SERVICE-NAME] [--timer-name TIMER-NAME]  # Show safe systemd user status for the Glance service and timer.
├── servers  # Collect and render the `服务器` Glance page.
│   ├── candidates [--config SSH-CONFIG] [--inventory-config INVENTORY-CONFIG]  # Print selected server aliases without probing hosts.
│   ├── collect [--alias ALIASES] [--inventory-config INVENTORY-CONFIG] [--default-candidates] [--output OUTPUT-PATH] [--timeout TIMEOUT] [--workers WORKERS]  # Write a server-status JSON snapshot from read-only SSH probes.
│   ├── render-page [--data DATA-PATH] [--output OUTPUT-PATH] [--inventory-config INVENTORY-CONFIG] [--page-name PAGE-NAME] [--page-slug PAGE-SLUG] [--widget-title WIDGET-TITLE]  # Write the `服务器` page YAML from server-status JSON.
│   ├── update-config [--data DATA-PATH] [--config CONFIG-PATH] [--output OUTPUT-PATH] [--inventory-config INVENTORY-CONFIG] [--page-name PAGE-NAME] [--page-slug PAGE-SLUG] [--widget-title WIDGET-TITLE]  # Write a config copy with the generated server page replaced.
│   └── validate-refresh [--previous PREVIOUS-PATH] [--next NEXT-PATH] [--allow-offline-regression]  # Validate a refresh snapshot without modifying either input.
└── sites  # Collect and render the `网站服务` Glance page.
    ├── collect [--inventory-config INVENTORY-CONFIG] [--output OUTPUT-PATH] [--gatus-db GATUS-DB]  # Write reviewed site cards and optional Uptime status to JSON.
    ├── export-covers [--data DATA-PATH] [--output-dir OUTPUT-DIR] [--public-base-url PUBLIC-BASE-URL] [--updated-data UPDATED-DATA]  # Write SVG covers and an optional updated inventory JSON.
    ├── render-page [--data DATA-PATH] [--output OUTPUT-PATH] [--page-name PAGE-NAME] [--page-slug PAGE-SLUG] [--widget-title WIDGET-TITLE]  # Write the `网站服务` page YAML from site-services JSON.
    └── update-config [--data DATA-PATH] [--config CONFIG-PATH] [--output OUTPUT-PATH] [--page-name PAGE-NAME] [--page-slug PAGE-SLUG] [--widget-title WIDGET-TITLE]  # Write a config copy with the generated website-services page replaced.
```

## 简洁树

`chatglance --tree-brief` 保留相同节点与说明，但省略参数和选项签名：

```text
chatglance
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
├── account-limits  # Render the `订阅详情` Glance page.
│   ├── json  # Write normalized, redacted account/quota JSON.
│   ├── render-page  # Write the `订阅详情` page YAML from account-limits JSON.
│   └── update-config  # Write a config copy with the generated account-limits page replaced.
├── disks  # Patch Glance server-stats disk display.
│   └── root-only  # Write a config copy that hides default snap/loop mountpoints.
├── home  # Patch ChatArch home-page widgets.
│   └── remove-widget  # Write a config copy with unavailable home-page widgets removed.
├── projects  # Generate Glance project dashboard pages.
│   ├── collect  # Write refreshed project inventory JSON from read-only GitHub metadata.
│   ├── render-page  # Write the `项目` page YAML from inventory JSON.
│   └── update-config  # Write a config copy with the generated project page replaced.
├── runtime  # Maintain a durable Glance service runtime.
│   ├── install-systemd  # Install, verify, enable, and optionally start user-level systemd units.
│   ├── maintain  # Update runtime config atomically and optionally restart a service.
│   ├── render-systemd  # Print user units or write them to an output directory.
│   ├── start  # Start the current Glance page through systemd user units.
│   └── status  # Show safe systemd user status for the Glance service and timer.
├── servers  # Collect and render the `服务器` Glance page.
│   ├── candidates  # Print selected server aliases without probing hosts.
│   ├── collect  # Write a server-status JSON snapshot from read-only SSH probes.
│   ├── render-page  # Write the `服务器` page YAML from server-status JSON.
│   ├── update-config  # Write a config copy with the generated server page replaced.
│   └── validate-refresh  # Validate a refresh snapshot without modifying either input.
└── sites  # Collect and render the `网站服务` Glance page.
    ├── collect  # Write reviewed site cards and optional Uptime status to JSON.
    ├── export-covers  # Write SVG covers and an optional updated inventory JSON.
    ├── render-page  # Write the `网站服务` page YAML from site-services JSON.
    └── update-config  # Write a config copy with the generated website-services page replaced.
```

## 边界

- `projects`、`servers`、`sites`、`account-limits`、`disks` 和 `home` 命令只写显式传入的输出路径，不应输出 GitHub token、代理凭据或账户敏感值。
- `runtime maintain` 可替换 runtime config，并可按显式选项重启 service。
- `runtime install-systemd` 与 `runtime start` 会修改或启动 user-level systemd 状态；`runtime status` 只回读安全状态字段。
