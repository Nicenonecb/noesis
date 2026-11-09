# 规划：一条消息同时发给多个 Code Agent

2026-11-09 起草，尚未实施。目标：在 NOESIS 应用里写一条消息，同时发给 Claude Code、Codex 和
DeepSeek Harness（DSH）；三者各占一个标签页显示回复，可以勾选其中一个作为「主体」。

## 体验

- 侧边栏新增「协作」（Agents）。顶部是输入框、工作目录选择和 agent 开关（默认三个全选）。
- 工作目录可以直接选待办任务里关联的文件夹，也可以用原生选择框另选；一次对话固定一个目录。
- 发送后出现三个标签页：`Claude Code`、`Codex`、`DSH`。标签上显示状态（运行中 / 完成 / 失败）和耗时；
  内容按 Markdown 实时显示（复用日报的安全渲染器），可以随时停止某一个。
- 每个标签页右上角有 ✓。勾选后该回复成为本轮「主体」，同一轮只能勾一个，可以改选。
- 继续追问时，三个 agent 各自接着自己的会话往下聊；历史对话在左侧按时间列出，可以重新打开。

## 已核实的本机情况

| Agent | 当前状态 | 非交互调用方式 |
|---|---|---|
| Claude Code | `claude` 不在 PATH，本机只有桌面版 Claude.app | `claude -p <消息> --output-format stream-json`，`--resume <id>` 续聊 |
| Codex | `codex` 已装，但启动报错：npm 包缺少平台二进制，需要重装 | `codex exec --json -C <目录> <消息>`，`codex exec resume <id>` 续聊 |
| DSH | 可用（0.2.1-rc.2） | `dsh --profile headless --json <消息>`，`--session-id <id>` 续聊，`-` 从 stdin 读消息 |

Claude Code 和 Codex 的参数按两者文档整理，需在修好安装后用 `--help` 逐项核对。

## 技术方案

- **调用方式**：由 NOESIS 本机服务为每个 agent 启动一个子进程（工作目录为所选文件夹），
  消息通过 stdin 传入，不拼进命令行，避免出现在进程列表中。三个进程并行，互不等待。
- **适配层** `noesis/agents/`：每个 agent 一个适配器，负责组装命令、解析各自的 JSON 事件流，
  统一成 `{type: text|tool|done|error, ...}`，并记录会话 ID 以便续聊。新增 agent 只需加一个适配器。
- **推送到页面**：服务端用 Server-Sent Events（`/api/runs/<id>/events`）推送增量；页面断开后可以从
  已保存的记录恢复。停止按钮结束整个进程组；每个 agent 设置超时，默认 10 分钟。
- **存储**：数据目录 `runs/`，每次对话一个目录：`run.json`（消息、目录、各 agent 状态、会话 ID、主体选择）
  加各 agent 的事件记录，权限 0600，写入前脱敏。三个工具自己的会话文件仍会被现有采集器收进日报，
  用会话 ID 标记「来自 NOESIS 协作」，避免日报里重复出现。
- **安全默认**：首版只读，让 agent 回答和读代码，不改文件（Claude Code 用 plan 权限模式，Codex 用
  `--sandbox read-only`；DSH 的权限控制方式待确认）。三个 agent 同时改同一仓库会互相覆盖，
  写入模式放到后续版本，每个 agent 在各自的 git worktree 中工作。
- **配置**：`config.toml` 新增 `[agents]`，可配置每个 agent 的可执行文件路径、是否启用、默认模型和超时；
  `noesis doctor` 检查三者是否可用。

## 分阶段

1. **准备**：重装 Codex、让 `claude` 命令可用；增加 `[agents]` 配置和 `doctor` 检查。
2. **命令行**：`noesis ask "消息" --dir <目录>`，并行调用并输出结果；用假 agent 脚本做离线测试。
3. **应用界面**：「协作」页、三标签实时显示、停止、✓ 主体、历史列表。
4. **续聊**：在同一对话中追问，各 agent 续接自己的会话。
5. **写入模式（可选）**：每个 agent 独立 worktree，完成后对比改动，把主体的改动合并回来。

## 需要你决定

1. **✓ 主体之后做什么**：只做标记方便回看？下一轮追问时，把主体回复作为共同上下文发给另外两个？
   还是导出（复制、存进待办备忘、写入日报）？
2. **首版只读**是否可以，还是一开始就需要改代码？
3. **联网约定**：AGENTS.md 规定只有 `digest/client.py` 可以联网。NOESIS 自身不会联网，但它启动的
   agent 会访问各自的服务，需要你同意在 AGENTS.md 中补充这条例外。
4. **模型与费用**：三个 agent 用各自的默认模型，还是在设置里统一指定？
