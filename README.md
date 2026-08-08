<div align="center">
    <a href="https://pypi.python.org/pypi/chatglance">
        <img src="https://img.shields.io/pypi/v/chatglance.svg" alt="PyPI version" />
    </a>
    <a href="https://github.com/ChatArch/chatglance/actions/workflows/ci.yml">
        <img src="https://github.com/ChatArch/chatglance/actions/workflows/ci.yml/badge.svg" alt="Tests" />
    </a>
</div>

<div align="center">

[English](README.en.md) | [简体中文](README.md)
</div>

# chatglance

`chatglance` 是 ChatArch/WZHECNU Glance dashboard 的 Python 生成与运维 CLI。

它不是 NPM 项目，也不是重新实现 Glance 后端：上游 Glance 仍然是 Go 单二进制 dashboard server；`chatglance` 负责把 ChatArch 项目清单、Glance YAML 页面、inline HTML 表格和安全运维补丁组织成可复用的 Python 包/CLI。

## 当前能力

- 从 repository inventory JSON 生成 Glance `项目` page。
- 当前 page tabs 固定为：`最近提交`、`待处理 PR / Issue`、`分类`、`一览表`。
- `待处理 PR / Issue` 只显示 PR/Issue 非 0 的仓库，并按 `(PR, Issue, 最近提交)` 降序。
- 生成 config 副本时清理 legacy generated pages：`Projects`、`ChatArch Projects`、`ChatArch Projects List`。
- 为 Glance `server-stats` 写入 root-only Disk 配置：`hide-mountpoints-by-default: true` + `mountpoints: /`，避免 snap/loop mount 出现在 Disk popover。
- 维护 durable runtime：一次性 `runtime maintain` 可原子更新 live config、备份、校验，并在内容变化时可选重启 systemd user service。
- 渲染 systemd user units：主服务仍直接启动 upstream Glance Go binary；维护任务是独立 oneshot/timer，不是 Python wrapper。

## 快速开始

```bash
pip install -e ".[dev]"
chatglance --help
chatglance --tree
chatglance --version
python -m pytest -q
python -m build
```

## CLI 示例

只生成 `项目` page YAML：

```bash
chatglance projects render-page \
  --data /path/to/chatarch-projects.json \
  --output playground/projects-page.yml
```

把生成页写入一个 Glance config 副本：

```bash
chatglance projects update-config \
  --data /path/to/chatarch-projects.json \
  --config /path/to/glance.yml \
  --output playground/glance.with-projects.yml
```

把 `server-stats` Disk 改成只显示 root 分区，写入 config 副本：

```bash
chatglance disks root-only \
  --config /path/to/glance.yml \
  --output playground/glance.root-disk.yml
```

维护一个 durable Glance runtime（默认 `~/.chatarch/glance`）：

```bash
chatglance runtime maintain \
  --runtime-home ~/.chatarch/glance \
  --restart-service chatarch-glance.service
```

生成推荐 systemd user units：

```bash
chatglance runtime render-systemd \
  --runtime-home ~/.chatarch/glance \
  --chatglance-bin ~/.chatarch/venv/bin/chatglance \
  --output-dir playground/systemd
```

## 运行态边界

推荐拓扑是 **systemd 直接运行 Glance，chatglance 只做维护**：

- 主服务：`chatarch-glance.service` 直接执行 `~/.chatarch/glance/bin/glance -config ~/.chatarch/glance/config/glance.yml`。
- 内容数据：repository inventory JSON、缓存和生成快照放在 `~/.chatarch/glance/data/` 或 `~/.chatarch/glance/cache/`。
- live config：`~/.chatarch/glance/config/glance.yml`；更新前写备份到 `~/.chatarch/glance/config/backups/`。
- 维护：`chatglance runtime maintain` 是 oneshot，可由 `chatarch-glance-maintenance.timer` 周期触发。
- 不建议加 Python 长驻 wrapper：wrapper 会把 server 生命周期和内容生成耦合，反而不利于 systemd 重启、日志、健康检查和回滚。

## 安全边界

- CLI 默认写 output file，不默认覆盖 live `glance.yml`。
- 不保存或输出 Glance auth、password hash、GitHub token、proxy credential。
- live runtime、logs、backups、全量实时 JSON 快照默认不进源码仓库。
- 后续如需动态表格、搜索、中英文切换，再考虑增加小型静态前端层；当前 Python CLI 是基础层。
