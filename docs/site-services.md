# 网站服务：默认 SVG 与部署配置

## 默认不依赖图床

省略 `cover_url` 时，卡片使用内置 SVG data URI。页面 YAML 自带图片，无需上传图片，也无需额外静态资源服务。SVG 的地址文案读取服务实际 `public_url`，不再从服务名拼接固定域名；文案不展示 URL 中的账号、密码、query 或 fragment。标题、简介、颜色和现有卡片布局保持不变。

外部图片仍是显式选项：设置某个服务的 `cover_url` 即可使用自定义图片。要把已有站点全部改回默认 SVG，应从 runtime inventory 移除 `cover_url` 并重新 collect/render；只修改已生成页面会被后续刷新覆盖。`sites export-covers` 只导出 SVG 文件，不能导出整套站点。

## 部署地址的唯一来源

所有真实部署值留在 runtime inventory 或现有 ChatEnv `ChatGlance` active profile；不应写进 Python 默认值或提交到仓库。

| ENV | 对应 inventory `page` 字段 | 含义 |
|---|---|---|
| `CHATGLANCE_SITES_PUBLIC_DOMAIN` | `public_domain` | 公网 DNS 后缀，用于生成 `https://<name>.<suffix>/` |
| `CHATGLANCE_SITES_LOCAL_DOMAIN` | `local_domain` | 可选内部 DNS 后缀，仅供探测，不展示在卡片上 |
| `CHATGLANCE_SITES_UPTIME_BASE_URL` | `uptime_base_url` | 可选 Uptime HTTP(S) 根地址，可以带路径前缀 |

优先级：**服务显式 URL/host > inventory page defaults > 进程 ENV > ChatEnv active profile**。没有内置生产域名。`page` 中显式空字符串可以清空对应的 ENV 默认值。

- 没有 `public_url` 且没有公网后缀时，采集明确报错；不会指向任何默认生产站点。
- 内部后缀为空时，不生成 `local_host`。
- Uptime 地址为空时，不生成监控跳转。
- DNS 后缀不能含协议、端口或路径；非标准入口用单服务 `public_url` 覆盖。
- Uptime base URL 不能含账号、密码、query 或 fragment。
- `chatenv test -t chatglance -I` 可做配置校验，不发网络请求。

下面使用保留示例域名，不是可直接访问的真实服务：

```bash
export CHATGLANCE_SITES_PUBLIC_DOMAIN=public.example.org
export CHATGLANCE_SITES_LOCAL_DOMAIN=internal.example.org
export CHATGLANCE_SITES_UPTIME_BASE_URL=https://status.example.org/
```

这些键也可以通过 ChatEnv 的 profile 编辑界面存入 `ChatGlance` active profile。不要新建另一套平行的 profile 存储。

如果选择 ENV 管理，inventory 可以保持简单：

```yaml
sites:
  - name: docs
    title: Docs
    description: 项目文档入口。
    cover_summary: Project documentation
  - name: portal
    title: Portal
    public_url: https://portal.example.org/tools/
    description: 独立域名或路径入口。
```

`examples/site-services.example.yml` 展示的是另一种方式：显式 `page` 默认值。使用 ENV 时应删除示例中的三个 `page` 地址字段，否则 page 值按上述优先级覆盖 ENV。

## 生成与验证

```bash
chatglance sites collect --inventory-config /path/to/site-services.yml --output playground/site-services.json
chatglance sites render-page --data playground/site-services.json --output playground/site-services-page.yml
chatglance sites update-config --data playground/site-services.json --config /path/to/glance.yml --output /path/to/glance.candidate.yml
/path/to/glance -config /path/to/glance.candidate.yml config:validate
```

需要最新监控状态时，在 `collect` 上显式传入 `--gatus-db /path/to/gatus.db`。以上命令不会创建 Nginx/DNS 入口，也不会复制被链接的网站。

## 新机器迁移边界

代码仓库提供渲染器、采集逻辑、刷新脚本和示例；运行中的页面配置、真实 inventory、JSON 快照、账号态和系统服务不由 Git 自动同步。当前没有整站 `export/import` 或 `backup/restore` 命令。

迁移可以分两层：

1. **恢复展示**：准备匹配平台的 Glance binary，并迁移经过安全处理的 `glance.yml` 与所需页面快照；默认 SVG 自包含，无需搬图床。原生 RSS/天气等 widgets 仍需要对应数据源。
2. **恢复持续更新**：另行准备 ChatGlance 及依赖包、仓库刷新脚本、runtime inventory/覆盖规则、ChatEnv/账号授权、必要 SSH 与网络权限，以及目标机器的 user systemd 单元。不要直接复制旧 venv 或把旧机器绝对路径当作可移植路径。

`runtime render-systemd/install-systemd` 只负责其声明的 Glance 主服务和维护任务，不能代替所有站点自定义 wrapper、采集定时器、反向代理或外部服务的迁移。真实 auth、token 和完整 live config/backup 应走受控备份与授权迁移，不进仓库。
