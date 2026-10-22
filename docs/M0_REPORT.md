# NOESIS · 智穹 M0 验收报告

日期：2026-10-22（Asia/Shanghai）。

名称与路径已统一更新为 **NOESIS · 智穹**。本次改名后重跑 43 项测试全部通过，
`noesis init`、`noesis doctor`、`python -m noesis --help` 及命令入口均已验证。
已有数据目录随项目名称迁移，配置与目标保留，数据库仍为空；M1 尚未开始。

M0 脚手架与命令已实现并验证。格式调研已完成本机可访问来源，Safari 真实 schema
因系统权限受阻待补验，Arc 本机未安装。按实施计划停在 M0，不进入 M1。

## 已交付

- 代码仓库：`~/code/noesis`；数据目录：`~/NOESIS`。
- Python 3.11 虚拟环境、pyproject.toml、noesis 命令入口；零运行时第三方依赖。
- init：创建配置/目标模板、私有目录、events/cursors 表及三组索引；重复运行保留数据。
- doctor：当前解释器、配置、数据库、会话文件、浏览器历史副本、Git 与权限诊断。
- Event：稳定 ID、UTC 固定微秒精度、capture=high；数据库幂等写入、cursor 与事务回滚。
- 为落实“先脱敏再入库”，提前实现共享脱敏模块及数据库写入边界；后续 Markdown 也必须复用。
- docs/FORMAT_NOTES.md：CC、Codex 实测结构，Chrome 实测 schema，未验证来源的明确标注。
- 合成 JSONL / SQL fixture，包括注入、工具结果、重复通道、未知/损坏行、WAL 与浏览器时间。
- 后续模块目录预留。install.sh 明确提示尚未实现，不安装任何系统集成。

## 验证结果

| 验证 | 结果 |
|---|---|
| `.venv/bin/python -m pytest` | 43 passed |
| `.venv/bin/noesis init && .venv/bin/noesis doctor` | 命令链退出 0，诊断正常完成 |
| `.venv/bin/noesis doctor --strict` | 退出 1：Safari 读取被拒绝，未掩盖权限缺口 |
| 数据库 | schema v1；events=0，cursors=0，尚未采集任何事件 |
| 重复初始化 | 保留自定义配置、goals 与事件，建表幂等 |
| 增量基础 | 重复事件去重，异常时事件和 cursor 一起回滚 |
| 脱敏 | 每种要求的模式均有正反例；嵌套 metadata、URL、raw_ref 与 cursor 覆盖 |
| 历史库副本 | 合成 WAL 场景读取成功，原库与 WAL 字节未改变 |
| 浏览器时间 | 合成 Chromium/Safari 时间换算到同一 UTC 时刻；真实浏览器 UI 对照留到 M3 |
| 离线约束 | 依赖和 editable 安装使用 --offline；测试禁止 socket 连接；运行时代码无网络调用 |

doctor 默认退出 0 代表“诊断完成”，**不代表所有权限齐全**。
无法读取来源用 ❌；需在 Hammerspoon/launchd 上手动验证的权限用 ⚠️；未发现可选应用用 ⚪。

## 格式调研的关键结果

1. CC 的 tool_result 与 api-request-blob 不能混成用户输入；thinking 不入库。
2. Codex 的 role=user 包含 AGENTS、环境、Page 上下文注入，需要识别并剥离包装。
3. Codex 新版存在 response_item 与 item_completed 双通道；助手消息可同 id 同文本重复，
   用户消息 id 不一定对应，M1 不能只靠 role 或 id 去合并两条通道。
4. Codex 正常 user 记录的 client_authored 可以为 false，不能把它当作可靠的过滤条件。
5. Chrome Default 实际 schema 已记录；Safari / Arc 的 fixture 明确标为未验证假设。

## 集中列出的手动事项

### Safari：M3 前处理，再补本机格式核验

在“系统设置 → 隐私与安全性 → 完全磁盘访问权限”核对启动采集的应用和解释器。
本次实际入口及解析后的二进制为：

```text
/Users/justin/code/noesis/.venv/bin/python
/opt/homebrew/Cellar/python@3.11/3.11.15_1/Frameworks/Python.framework/Versions/3.11/bin/python3.11
```

视 macOS 的调用链归属，也可能需要给启动终端或 Codex 授权并重启应用；应以再次运行
doctor 的读取结果为准。Homebrew 升级可能改变真实二进制路径，届时需重新核对。
M5 的 launchd 必须使用最终 plist 中的实际解释器再验，不能沿用当前进程结果。

### 快捷键收藏：M4 前集中处理

- 安装 Hammerspoon（本机尚未发现）。
- 给 Hammerspoon 辅助功能和屏幕录制权限；通过实际快捷键截图验证权限归属。
- 首次运行时允许实际 Apple 事件调用方控制浏览器；在“隐私与安全性 → 自动化”核对。
- Chrome：显示 → 开发者 → 允许 Apple 事件中的 JavaScript。
- Safari：开发 → 允许 Apple 事件中的 JavaScript；若无开发菜单先启用开发者功能。
- Arc 不使用则无需安装；需要时安装后补测 schema 与 AppleScript。

这些事项不阻止 M1 的代码实现；按照约定仍须先由用户确认 M0，再进入 M1。

## 已知边界与后续待办

- 尚无 collect、capture、annotate、build-daily、digest、stats；后续里程碑逐一实现。
- 尚未安装 Hammerspoon 配置、OCR 或 launchd，没有后台采集、定时任务或网络发送。
- Safari 真库、Arc、多 Profile 真实环境未验证；Chrome 实测时无 WAL，WAL 仅在合成测试验证。
- 正则脱敏不能识别所有自由文本秘密，也不遮挡截图像素；截图保留本地原图是 M4 的明确边界。
- cursor.key 使用原始键的 SHA-256，避免脱敏标记导致不同文件的 cursor 混淆。
- M5 要处理 23:30 渲染与“次日完整昨日日志”之间的时间差，补齐末半小时及睡眠漏跑。
- 未推送远程仓库；真实会话、浏览记录、截图及运行数据库均不进入 Git。

## 使用入口

```sh
cd ~/code/noesis
source .venv/bin/activate
noesis init
noesis doctor
```

无需激活时可直接执行 `~/code/noesis/.venv/bin/noesis doctor`。
下一步：用户确认后开始 M1（Claude Code / Codex 增量采集与真实数据抽查）。
