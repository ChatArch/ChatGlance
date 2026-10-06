# 自包含部署与 CLI 管理

## 五层边界与兼容性

1. Git 跟踪的源码负责公共模板、Python API 与文档。
2. 安装的 **ChatGlance 0.3.0 wheel** 负责全部业务逻辑；服务入口不依赖 checkout。
3. 单独维护的 **ChatArch/glance chatarch-v0.2.1** 负责网页、登录和会话；不需要新 Go 特性时兼容维护版 0.1.0。未修改上游不能作为登录后端的直接替代品。
4. 标准 typed ChatEnv 保存敏感配置，home 下 `glance/` 保存私有运行配置、清单、快照与已校验二进制。
5. 可选 Linux user-systemd 单元是薄入口；nginx 由操作者单独管理。

项目「概览」旁的原生刷新图标需要维护版 Go `chatarch-v0.2.1` 或更新版本的 `header-controls-url` 支持；旧二进制不能显示这个入口。Python 与 Go 版本独立，升级时先部署已校验的新 Go 二进制，再重渲染页面。

管理部署支持 Linux/POSIX、user systemd、隔离的 Python 安装环境与适合目标架构的维护版 Go 二进制。init/渲染可以不使用 systemd。安装不自动发布、迁移生产、启动服务、发现 SSH 主机或消费重置卡。本指南不是已完成生产切换的声明。

## 完整通用目录

```text
repository/
├── src/chatglance/managed.py + managed_cli.py  # 可导入逻辑与薄 CLI
├── src/chatglance/resources/                 # 下表列出的全部公共资源
├── scripts/ + examples/                     # 旧薄入口、通用示例
└── docs/                                    # 双语文档、真实命令树
CHATARCH_HOME/
├── envs/                                    # 标准私有 provider 存储
└── glance/
    ├── bin/glance + glance.provenance.json   # 已校验程序及来源摘要
    ├── config/                              # ENV 引用、私有主机/站点清单
    ├── data/ + cache/ + logs/                # 快照、共享刷新锁
    ├── scripts/                             # 打包的薄 shell 入口
    └── private/managed.json + managed-backups/ # 所有权清单与私有备份
user-systemd-directory/
├── chatarch-glance.service
├── chatarch-glance-refresh-pages.service + .timer
├── chatglance-reset-controls.service        # 可选认证控制
└── chatarch-glance-maintenance.service + .timer # 仅显式启用
```

默认运行目录为 `chatenv.get_paths().home_dir/glance`；`CHATARCH_HOME` 选择 provider home，`--runtime-home` 选择运行目录。管理清单记录有效 provider home，刷新、校验与控制均使用同一环境。登录名、账号绑定、主机清单和快照都是私有输入，不进入公共源码。

## 从零配置、安装、检查、启动

先在隔离环境安装经过审查的 wheel，再使用该环境 CLI。下列命令也是从零安装 shell 流程；打包的 shell 脚本仅转交 CLI。

```bash
export CHATARCH_HOME="$PWD/isolated-home"
chatenv status
chatenv init -t chatglance -i
chatenv set -i
chatglance runtime paths
chatglance runtime init --with-auth
chatglance runtime install-binary --archive reviewed.tar.gz --sha256 EXPECTED_SHA256 --binary-version chatarch-v0.2.1+40_LOWERCASE_HEX
chatglance runtime install --page projects --interval 30min
chatglance runtime install --page projects --interval 30min --apply
chatglance runtime check
chatglance runtime status --runtime-home "$CHATARCH_HOME/glance" --live
chatglance runtime start --runtime-home "$CHATARCH_HOME/glance" --apply
```

摘要和版本占位符必须替换为**实际观察并审查的发行产物信息**。不猜测校验文件，不下载 unchecked latest。tar 中只允许一个普通 `glance` 文件；明确授权的 SHA256 允许执行有超时的 staged `--version`，要求精确的维护版标识 `chatarch-vMAJOR.MINOR.PATCH+40hex`。来源 JSON 记录实际 tag/source revision 和 archive/binary 摘要。

用 `chatenv set -i` 交互保存 `CHATGLANCE_LOGIN_USER`、`CHATGLANCE_LOGIN_SECRET`（严格标准 base64，解码**恰好 64 字节**）及完整 bcrypt `CHATGLANCE_LOGIN_PASSWORD_HASH`，不在 argv 保存密码/密钥。`chatenv list`、`chatenv use -t chatglance PROFILE` 管理标准 profile。**托管登录忽略继承的进程 `CHATGLANCE_LOGIN_*` 与索引 `CHATGLANCE_AUTH_*`**，启动/验证/控制服务只以选定 active EnvStore profile 为准。非认证的 owner、页面、cadence、端口、公网 origin 等配置仍允许进程环境优先；刷新流水使用同一 typed provider/process 优先级的 `CHATGLANCE_REFRESH_HISTORY_RETENTION_DAYS`（默认 30）和 `CHATGLANCE_REFRESH_HISTORY_MAX_BYTES`（默认 268435456），非法值拒绝。显式 CLI 参数覆盖默认。CRS consumerKey/OAuth/token 仍由原 provider 管理；GitHub 等使用共享 Token resolver，不新建密钥库。

没有登录配置时省略 `--with-auth`；已有无认证配置不能被 init 悄悄升级。默认仅回环监听、空清单无网络调用；先审查并添加需要的页面。机器排除策略只写私有 runtime `server-inventory.yml` 的 `inventory.exclude` / `inventory.excludes`；源码仅排除通用 `local` / `localhost`。`default_candidates: false` 保持关闭。

`runtime install` 默认仅计划、无写入；`--apply`/`--yes` 才执行 Go/单元校验、私有备份、逐文件原子替换和 daemon-reload。`--enable`、`--start` 必须另行显式选择。未知文件和符号链接拒绝覆盖；`--adopt-units` 仅授权替换选定且审查过的旧单元。检查 systemd 实际 `FragmentPath`、`DropInPaths`、`EnvironmentFiles`、`ExecStart`；选定单元 `.service.d/*.conf` 覆盖必须额外使用 `--retire-dropins` 审核后私有备份、撤销并读回生效命令。其他覆盖或意外启动命令拒绝。路径正确引用空格/百分号，名称拒绝 URI/换行/specifier 注入。已有所有权拓扑不能被悄悄抛弃；停止并审查后再改变所有权。

## 原运行目录原地接管，不导出密钥

只选择同一 provider home 的旧 runtime，先备份和 dry-run：

```bash
chatglance runtime adopt --runtime-home "$CHATARCH_HOME/glance" --public-origin https://example.invalid --control-port 5679
chatglance runtime adopt --runtime-home "$CHATARCH_HOME/glance" --public-origin https://example.invalid --control-port 5679 --apply
chatglance runtime install --runtime-home "$CHATARCH_HOME/glance" --web-unit chatarch-glance.service --refresh-unit chatarch-glance-refresh-pages.service --refresh-timer chatarch-glance-refresh-pages.timer --page servers --page account-limits --page projects --interval 30min --adopt-units
chatglance runtime import-env --runtime-home "$CHATARCH_HOME/glance" --file config/legacy.env --retire
# 审查 key 和 provider 冲突后为 import-env 添加 --retire --apply。
# 审查旧单元 drop-in 后添加 --retire-dropins；审查计划后再添加 --apply。
```

adopt 保留**完全相同签名 key 和所有 bcrypt hash**，因此既有登录会话保持有效。全部账号进入敏感 typed `CHATGLANCE_LOGIN_ACCOUNTS`，安全索引变量注入子进程；Go 校验通过后才把 auth/port 替换为 `${ENV_NAME}`。保留页面/组件语义，生成快照字节不变；YAML 格式和注释可能规范化。冲突默认失败，仅 `--replace-provider` 明确授权覆盖；其他 provider 策略不丢失。输入变更中止发布。dry-run 只报计数/键名；备份含原密钥，必须如 provider 一样保密，绝不能发布。

`runtime import-env --file config/NAME.env` 或 `private/NAME.env` 只读取选定、runtime 相对路径下的**字面 env 赋值**，不执行 shell。仅导入 ChatGlance typed schema 字段及旧 `PROFILES` 到 `CHATGLANCE_ACCOUNT_LIMITS_PROFILES`；`MODELS` 和其他未知键只报告**键名**，不隐式迁移。冲突需要 `--replace-provider`。`--retire --apply` 私有备份源文件、写 active provider，typed 读回成功后才删除旧文件；确认逐账号策略/登录配置后才通过 `runtime install --retire-dropins --adopt-units --apply` 撤销旧 EnvironmentFile 覆盖。绝不把 unit drop-in 当脚本执行；回滚编号可恢复 provider/源文件字节。

采用原服务名，避免 portable 与原服务重复运行。显式 `--scheduled` 才允许既有逐账号策略执行；首次默认关闭，重装省略选项时保持原页面/cadence/scheduled。选 account-limits 不等于授权消费。原生刷新共享锁、校验和发布后，只在内容变化时对所属 web 服务重启一次；不强制 `--no-restart`，不增加 scheduler/无条件第二次重启。install/update/maintenance 在 collector active、activating、reloading 时拒绝冲突。maintenance 仅显式开启。

## 控制、维护、更新与回滚

控制需要完整登录、私有 account-limits 页面、HTTPS `CHATGLANCE_PUBLIC_ORIGIN` 和回环控制端口。审查后 `runtime install --controls --page account-limits --apply` 安装，`runtime controls` 显式前台运行。可选 `runtime install --maintenance --apply`。不写重复凭据 EnvironmentFile。nginx 示例包含同源 `/_chatglance/reset-policy/`、登录路由及 `/项目` 到 `/projects` 旧路径重定向；操作者设置域名/TLS/上游端口，CLI 不安装或 reload nginx。

```bash
chatglance runtime check --runtime-home "$CHATARCH_HOME/glance" --live
chatglance runtime restart --runtime-home "$CHATARCH_HOME/glance"
chatglance runtime stop --runtime-home "$CHATARCH_HOME/glance" --apply
chatglance runtime update --runtime-home "$CHATARCH_HOME/glance" --archive reviewed-next.tar.gz --sha256 EXPECTED_SHA256 --binary-version chatarch-v0.2.1+40_LOWERCASE_HEX --apply --restart
chatglance runtime rollback --runtime-home "$CHATARCH_HOME/glance" --backup BACKUP_ID
chatglance runtime rollback --runtime-home "$CHATARCH_HOME/glance" --backup BACKUP_ID --apply
```

start/stop/restart/update/rollback 默认仅计划；操作对象限制在所有权清单。check 对非托管 runtime 或生效 fragment/drop-in/environment/启动命令不匹配直接失败；区分 Python 安装、实际二进制版本/摘要、Go 配置和可选在线 PID；输出仅摘要/计数/存在性，不输出原 systemd 环境、登录材料或账号标识。update 必须提供校验产物，配置验证后才替换 binary/provenance，可选所属 web restart；失败则还原旧 binary，尝试正常重启此前运行的 web 并读回状态/PID；恢复失败明确报错。install 部分 enable/start 失败会撤销新动作，恢复文件/reload 并检查旧活跃单元。手动 rollback 预先检查全部目标和备份摘要，拒绝外部修改/未知文件；恢复文件并 reload，但**不撤销 enable/start，也不自动重启旧进程**，审查后显式 restart。

## 全部打包公共资产清单

以下每项都在 `src/chatglance/resources/`，随源码提交跟踪，wheel/sdist 包含；`assets.json` 是机器可读清单。单元不包含敏感值。

| 仓库资源 | 打包/运行作用 | 私有输入 |
| --- | --- | --- |
| `glance.yml` | `config/glance.yml` 起始模板 | 登录 ENV 引用、审查页面/端口 |
| `server-inventory.yml` | 空主机清单 | SSH 别名与排除策略 |
| `site-services.yml` | 空站点清单 | 审查站点 |
| `reverse-proxy.example.conf` | nginx 审查示例 | 域名/TLS/回环端口 |
| `start.sh` | 薄前台启动 wrapper | ChatEnv home |
| `install.sh` | 薄 init wrapper，非服务激活 | ChatEnv home |
| `refresh.sh` | 薄原生刷新 wrapper | 选定页面 |
| `web.service` | 已安装包 env bridge 启动 Go | typed 登录配置 |
| `refresh.service` | 所属原生刷新 | 清单与 provider 策略 |
| `refresh.timer` | 页面刷新 cadence | 审查 schedule |
| `controls.service` | 可选认证开关服务 | Go 登录/provider 账号 |
| `maintenance.service` | 可选原生维护 | 运行配置 |
| `maintenance.timer` | 可选维护 cadence | 审查 schedule |
| `assets.json` | 完整资源清单 | 无 |

可复用 API：`chatglance.managed.install_runtime`、`adopt_runtime`、`runtime_status`、`service_action`、`update_binary`、`rollback_runtime`、`refresh_managed`、`maintain_managed`。旧 `render-portable` / `install-systemd` 保持兼容；新管理部署使用上述所有权流程。[CLI 参考](cli.md) 与仓库 `docs/cli-tree.md` 对真实 `chatglance --tree` / `--tree-brief` 测试，参数以它们为准。

源码专用旧开发入口（Git 跟踪、包含在 sdist，**不是 wheel 生产入口**）：

| 仓库路径 | 源码/运行作用 | 私有输入 |
| --- | --- | --- |
| `scripts/chatglance-from-source` | checkout 开发入口 | 开发路径 |
| `scripts/collect-codex-account-limits.py` | 旧薄采集 wrapper | 既有 ChatCRS provider |
| `scripts/refresh-live-pages.sh` | 旧开发刷新入口 | runtime home |
| `scripts/refresh-manual.sh` | 旧手动刷新入口 | runtime home |
| `scripts/refresh-projects-page.sh` | 旧项目页面入口 | 私有项目清单 |
| `scripts/refresh-server-status.sh` | 旧服务器页面入口 | 私有 SSH 清单 |
| `scripts/refresh-sites-page.sh` | 旧站点入口 | 私有站点清单 |
| `scripts/refresh-account-limits-page.sh` | 旧账号入口 | 既有 typed provider |
| `examples/server-inventory.example.yml` | 通用源码主机示例 | 真实别名只在 runtime |
| `examples/site-services.example.yml` | 通用源码站点示例 | 真实站点只在 runtime |

`assets.json` 同时列出 wheel 的 14 项资源（包括自身）及这 10 项源码专用资产。`src/chatglance/` 的安装包 Python 模块负责生产全部业务逻辑。`controls.service` 使用 `TasksMax=128`，不继承过小的旧 worker 限额。
