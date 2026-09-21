# 自动用卡小窗

卡片默认折叠重置卡信息；“自动用卡设置”打开居中小窗。预测只在小窗内显示，字体与配色继承现有Glance页面。

## 一个账号，一个开关

每个账号只有一个“自动用卡”开关，没有全局开关：

- **已暂停**：该账号开关关闭，不会自动用卡。
- **等待条件**：账号已开启，但上一次计划刷新的条件未满足或存在执行保护。
- **已就绪**：账号开关与该次计划刷新中的条件通过；实际消费若需要，会在同一次刷新内完成，不由页面或另一个定时器发起。

账号开关与业务条件列在同一执行清单中。每项显示该次计划刷新时自己的通过/未通过结果，标题显示“上次计划检查”时间；数据年龄不会把全部条件改写成第三种状态。关闭账号改变总体状态，不伪造原业务条件；修改一个账号不改变其他账号，也不使其他账号的表单版本失效。

预测为第三方滚动未来24小时概率，不是准确率或官方保证。大于配置阈值否决；来源无效、来自未来、缺失或超过2小时均拒绝。低概率不单独许可用卡。来源为 https://codexreset.org/ 的有效当前SSR loader，不使用历史对象、注释脚本、动画初值或48小时值。

## 同源部署

```bash
chatglance account-limits control-serve \
  --public-origin https://dashboard.example.org \
  --port 5679
```

仅监听IPv4 loopback。默认runtime为`$CHATARCH_HOME/glance`，可用`--runtime-home`覆盖；复用该runtime已有Glance登录，不创建账号、不复制密码。

```nginx
location ^~ /_chatglance/reset-policy/ {
    proxy_pass http://127.0.0.1:5679/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
}
```

反代保留Cookie和Origin，设置同源绝对前缀后重新生成页面：

```dotenv
CHATGLANCE_ACCOUNT_LIMITS_CONTROL_PATH=/_chatglance/reset-policy/
```

## 执行与安全

普通`account-limits collect`按各账号的`enabled`判断许可；缺省策略关闭。单次只读检查使用`--no-execute-resets`；不带`--scheduled`的`chatglance refresh`始终不消费。`--scheduled` 刷新先读取新鲜数据，再在同一次调用中判断并最多消费一张；页面查看/刷新不参与该动作。单次检查模式不是账号设置，不应展示为当前账号的“仅预演”。

开启账号须明确确认。写入要求有效既有登录、同源Origin、会话绑定短期一次性CSRF与该账号的配置revision；通过ChatEnv更新并回读。全局写操作被拒绝。页面不从快照直接兑换；实际执行仍有新鲜查询、墙钟复核、身份检查、持久预留、去重、冷却和未决结果保护。

主题脚本仅读取同源父页面的字体/颜色，并复用同源`/static/`样式。CSP只授权该固定脚本的精确哈希，不开放任意内联脚本、外部脚本或网络请求。Cookie、CSRF与凭据不进入项目报告或日志。

## 从旧全局字段迁移

旧`CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE`不再是支持的设置。检测到残留时扫描失败关闭，不能忽略旧false而悄悄启用全部账号。先暂停后台扫描和控制服务、备份现有配置，再使用ChatEnv显式迁移：

```python
import json
from chatenv import EnvStore, get_paths
from chatglance.config import ChatGlanceConfig

store = EnvStore(get_paths().envs_dir)
values = store.load_active(ChatGlanceConfig)
key = "CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE"
if key in values:
    raw = str(values[key]).lower()
    assert raw in {"true", "1", "yes", "on", "false", "0", "no", "off", ""}
    permitted = raw in {"true", "1", "yes", "on"}
    policies = json.loads(values["CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"])
    for policy in policies.values():
        assert type(policy["enabled"]) is bool
        policy["enabled"] = permitted and policy["enabled"]
    updated = dict(values)
    updated.pop(key)
    updated["CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"] = json.dumps(policies)
    assert store.load_active(ChatGlanceConfig) == values
    store.save_active(ChatGlanceConfig, updated)
    assert store.load_active(ChatGlanceConfig) == updated
```

同时从进程环境中移除旧字段，再恢复服务。这样保留旧的**实际生效状态**：原来受全局关闭阻断的账号迁移后显示关闭；之后只需打开希望启用的那个账号。其他设置、阈值与凭据保持不变。

Python接口：`reset_decisions.diagnose_account()`负责只读解释，`reset_control.make_control_server()` / `serve_controls()`提供受保护控制面；解释快照不是可消费授权。
