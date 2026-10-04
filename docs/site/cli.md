# 命令索引：按副作用分段

以下节点来自实际注册的 `chatglance --tree-brief`；具体参数以安装版本的 `chatglance --tree` 和 `chatglance <组> <命令> --help` 为准。只读、写候选与作用于 runtime 的命令不应混用。

## 访问与页面生成

```text
chatglance
├── access
│   ├── render-public
│   └── render-single-origin-optional-login
├── projects
│   ├── collect
│   ├── render-page
│   └── update-config
├── sites
│   ├── collect
│   ├── export-covers
│   ├── render-page
│   └── update-config
└── servers
    ├── candidates
    ├── collect
    ├── render-page
    ├── update-config
    └── validate-refresh
```

`access render-single-origin-optional-login` 向**指定私有路径**写同址候选；`access render-public` 是旧的 detached public **离线**配置/清单候选输出，不是推荐的第二站点部署。`projects collect` 获取元数据，`projects render-page` 生成页面片段，`projects update-config` 从指定的配置与 inventory 写配置副本。服务器与网站服务仅采集显式清单；不要在匿名资产目录放全量 inventory。

## 刷新与运行

```text
chatglance
├── refresh
├── runtime
│   ├── install-systemd
│   ├── maintain
│   ├── render-systemd
│   ├── start
│   └── status
├── home
│   └── remove-widget
└── disks
    └── root-only
```

`refresh` 使用运行时现有清单刷新已配置页面；手动模式不会兑换重置卡。`runtime maintain` 可以改写指定 runtime 配置；`install-systemd`、`start` 会操作 user-level 服务/定时器，需要额外审核。`render-systemd` 可只打印模板。详情见 [刷新与运行](operations.md)。

## 订阅与重置控制

```text
chatglance
└── account-limits
    ├── collect
    ├── control-serve
    ├── json
    ├── render-page
    └── update-config
```

`collect` 处理账号用量与重置日历，`control-serve` 是现有受认证保护的本地开关服务；是否执行计划内重置由显式 `refresh --scheduled` 与每账号策略决定，不能从渲染页面推断可以消费。运行真实账号前核查权限与当前配置。
