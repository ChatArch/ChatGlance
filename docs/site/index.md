# ChatGlance：从场景开始

ChatGlance 是 Glance 仪表盘的**配置生成与运维工具**，不是网站后端。它生成项目、服务器、网站服务和订阅页面，供现有 Glance 实例读取。选择你要完成的工作，而不是从整棵命令树开始：

<div class="grid cards" markdown>

-   :material-account-key-outline: **同一网址，访客可读与登录后完整视图**

    ---

    从 [项目与访问](projects.md) 了解 `public: true`、`authenticated-columns` 和同一路径 `/项目` 的权限边界。候选配置**不是**上线命令。

-   :material-rocket-launch-outline: **新建可定制的站点**

    ---

    [快速开始](quickstart.md) 从受控的 Glance 配置、合成数据和候选校验开始；不会安装服务或发布文件。

-   :material-refresh: **刷新已有页面**

    ---

    [刷新与运行](operations.md) 解释手动只读、定时计划、数据回退和服务生命周期的分界。

-   :material-console: **查命令和责任边界**

    ---

    [分段 CLI 索引](cli.md) 按访问、项目、刷新和运行分组；[架构与能力](architecture.md) 说明源代码与运行时各自负责什么。

</div>

!!! warning "依赖的 Glance 能力"
    官方 Glance v0.8.5 **没有**这里所需的 `public` 页面和 `authenticated-columns` 服务端会话选择。使用维护版 [chatarch-v0.1.0](https://github.com/ChatArch/glance/releases/tag/chatarch-v0.1.0) 的 Linux amd64 二进制，并校验发布页中的 `SHA256SUMS`。安装 Python 包不会自动替换现役 Glance；切换前仍需验证配置、匿名访问、登录和登出。

按 [快速开始](quickstart.md) 选择操作路径；服务部署和回滚边界见 [刷新与运行](operations.md)。
