# 本机数据格式调研（M0）

M1 更新（2026-10-25）：采集器已实现，详见 `M1_REPORT.md`。
本机新增观察到 `response_item.payload.type=configuration_update`，是配置事件，已过滤。
下文 M0 边界与证据描述保留为历史调研记录。

调研日期：2026-10-22，时区 Asia/Shanghai。只读取本机文件；没有网络请求。
本文仅记录结构、字段名及过滤规则，不保存真实消息、会话标识、仓库名、URL、标题或邮箱。
`tests/fixtures/` 全部是从零编造的示例，不能从中还原用户记录。

## 证据范围与状态

| 来源 | 本机核验 | 范围 / 限制 |
|---|---|---|
| Claude Code | 已核验 | 4 个文件的记录结构；另检索到 31 个 JSONL；样本版本 2.1.284 / 2.1.286 / 2.1.304 |
| Codex sessions | 已核验 | 35 个文件的前 350 行；另抽读 4 个文件，单文件最多 32 MB；持续写入的文件可能变化 |
| Codex history | 已核验 | 现有文件逐行解析；不能据此推断桌面版输入覆盖率 |
| Chrome Default | 已核验 | 对真实 History 的临时副本查表结构与 quick_check；当时没有 WAL |
| Chrome 多 Profile | 未在本机观察到 | 目录匹配与隔离需在 M3 用合成样本测试 |
| Safari | 被权限阻止 | History.db 存在，读取报 PermissionError / EPERM；没有查到真实 schema |
| Arc | 未安装 / 未发现数据 | 不能将 Chrome 的核验结果当成 Arc 实测结果 |

权限受阻的来源在后续里程碑补测；没有用网络文档或推测冒充本机结果。

## Claude Code

路径：`~/.claude/projects/<encoded-project>/<session>.jsonl`。
以 UTF-8 JSONL 读取；每行一个独立对象。主会话文件之外可能有子目录，M1 需结合
`isSidechain` 和实际路径处理子 agent；本次抽样没有观察到 true 的 sidechain。

用户行的实测字段包含：`type`, `uuid`, `parentUuid`, `sessionId`, `timestamp`,
`cwd`, `gitBranch`, `isSidechain`, `isMeta`, `version`, `message`，以及可选的
`promptId`, `promptSource`, `sourceToolAssistantUUID`, `sourceToolUseID`, `toolUseResult` 等。
`message` 有 `role`、`content`；content 可以是字符串或 block 数组。

助手行的 `message.type` 为 `message`，还包含 `id`, `model`, `usage`、停止原因等。
block 实测有 `text`, `tool_use`, `thinking`, `tool_result`, `image`。
一个 assistant 行可能只有工具调用或 thinking，没有可展示的回复正文。

已观察到的外围记录包括：`queue-operation`, `attachment`, `last-prompt`,
`file-history-snapshot`, `file-history-delta`, `atis-latch`, `api-request-shape`,
`api-request-blob`, `api-request`, `custom-title`, `agent-name`, `system`, `cost-state`。
特别是 **api-request-blob.message.role 也可能是 user**，不能绕过顶层 type 去提取。

M1 解析约定：

- 顶层 type=user 且 message.role=user；排除 isMeta=true、配置要求跳过的 sidechain。
- 只取字符串或 text block；不读取 tool_result 的嵌套正文，不存图片、工具输出。
- 实测用户文本中有 `<system-reminder>` 注入。还需用合成样本覆盖已知控制包装；
  不可仅因用户正常文本提到 AGENTS 或环境字段就整条删除。
- 顶层 type=assistant 且 message.role=assistant；只取 text；thinking 永不存储。
  tool_use 只存工具名与安全的路径摘要，不能把 input 整体写入 metadata。
- 用顶层 uuid 作 source_id；message.id 可能关联分块，不能假设等同于独立行 id。
- cwd 推导 project；cwd、gitBranch 经脱敏后存 metadata。
- timestamp 应解析为带时区时间，再转成 UTC。异常行仅记录来源标识、行号及错误类型，
  不把失败行内容写进日志。

## Codex sessions：本机新格式

路径：`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`。
实测版本：`0.162.0-alpha.2`、`0.162.0-alpha.17.2`、
`0.163.0-alpha.10.2`、`0.163.0-alpha.11.1`。
顶层是 `timestamp`, `type`, `payload`，新记录还可能有 `ordinal`, `metadata`。

### 上下文与文本

- `session_meta.payload` 同时可能有 `id` 与 `session_id`，以及 cwd、timestamp、
  cli_version、source、thread_source、originator、git、history_mode 等。
  还出现 base_instructions 和账户字段；这些不是用户输入，不入库。
- `turn_context.payload` 有 cwd、turn_id、timezone、模型与权限配置等。
  cwd 可能更新；不能始终只用文件头。
- `response_item.payload.type=message` 时，role 有 user、assistant、developer。
  文本数组类型为 input_text / output_text；message.id 在本次样本中存在。
- assistant 的 **phase** 实测为 commentary / final_answer；不是 channel。
  可同时保留进度文本和最终回复，但不能重复采集它们的镜像记录。
- 顶层 metadata 可能含 client_authored、retained_source、user_input_order、mcp_attribution；
  payload.internal_chat_message_metadata_passthrough 可能含 turn_id、create_time、content_item_kinds。
  **实测正常 user 记录的 client_authored 也可以为 false，不能据此直接排除。**

### 自动注入与重复数据

实测以下内容虽然 role=user，却不是用户真正输入的正文：

- 以 `# AGENTS.md instructions` 开始的指令包装；
- `<environment_context>...</environment_context>`；
- `<external_codex_apps_open_page>...</external_codex_apps_open_page>`。

developer 消息中另有 `<permissions instructions>`、`<codex_apps...>` 配置注入。
排除 system/developer 角色。用户输入如果和包装混在同一条里，应只剥离确认的包装，
保留剩余真实输入；不能用“不包含某个关键词”作为过滤规则。

本机还有 `event_msg.payload.type=item_completed`，其 payload.item.type 包括：

| item.type | 实测字段 / 内容 |
|---|---|
| UserMessage | id, client_id, content；块 type=text，含 text、text_elements；也有 local_image |
| AgentMessage | id, content, phase, delivery, questions；块 type=Text（大写 T） |
| Reasoning | raw_content, summary_text；不可采集 |
| CommandExecution / McpToolCall / FileChange / Extension | 工具执行信息；不可当作用户输入或回复 |
| ContextCompaction | 压缩标记；不可当作新消息 |

抽查中 AgentMessage 与 response_item.message 的 id 和文本可完全相同。
**UserMessage 的 id 与对应 response_item 的 id 不一定相同。**
M1 应选定一个主通道，再对备选通道按会话、回合/输入顺序和文本进行交叉核对。
不能同时无条件写入，也不能全局按正文去重，否则用户重复发送同一句话会被吞掉。
`task_complete.last_agent_message` 也只是最终回复副本，不是新回复。

其他实测类型：world_state、token_usage_record、response_item.reasoning、
function_call、function_call_output、custom_tool_call、custom_tool_call_output、additional_tools，
以及 event_msg 的 task_started、token_count、thread_settings_applied 等，均不当作对话正文。

### history.jsonl 和旧格式

`~/.codex/history.jsonl` 的实测键为 session_id（字符串）、ts（整数）、text（字符串）。
ts 按 Unix 秒处理；应和会话记录交叉核对。文件存在不代表覆盖所有桌面输入。
只有在不能匹配主会话记录时才考虑补充，避免重复计数。

本机抽样未发现计划中常见的旧 event_msg.user_message / agent_message 格式。
`codex_legacy_candidate.jsonl` 是为 M1 准备的**假定兼容样本**，不是本机格式证据。
未知类型应容错并记录不含正文的 warning；不能悄悄套用不匹配的解析器。

## 增量读取需要覆盖的边界（M1）

记录字节偏移，使用二进制 seek，不使用字符偏移。尚未以换行结束的尾行留到下次；
完整但损坏的行跳过并记录类型/行号。文件缩短从头读并按稳定 id 去重。
文件轮换或同长度重写需用 inode/指纹辅助检测，不能只检查大小。
事件写入与 cursor 更新必须在同一事务里，避免崩溃后漏采；回填不能破坏正常增量位置。
cursor API 接收原始逻辑键，数据库 key 列存其 SHA-256；调用方不需要预先哈希。
这样既不落盘原始路径，又不会因两段凭据被替换成同一脱敏标记而混淆 cursor。
raw_ref 记录原始路径及行号，仅存在本地数据库，不复制原始内容进仓库。

## Chrome 历史库（本机已核验）

路径：`~/Library/Application Support/Google/Chrome/{Default,Profile *}/History`。
本机仅发现 Default。通过只读临时副本查询，quick_check=ok。

实测 `urls`：id INTEGER PK、url LONGVARCHAR、title LONGVARCHAR、visit_count INTEGER、
typed_count INTEGER、last_visit_time INTEGER、hidden INTEGER。

实测 `visits`：id INTEGER PK、url INTEGER、visit_time INTEGER、from_visit INTEGER、
external_referrer_url TEXT、transition INTEGER、segment_id INTEGER、visit_duration INTEGER、
incremented_omnibox_typed_score BOOLEAN、opener_visit INTEGER、originator_cache_guid TEXT、
originator_visit_id INTEGER、originator_from_visit INTEGER、originator_opener_visit INTEGER、
is_known_to_sync BOOLEAN、consider_for_ntp_most_visited BOOLEAN、visited_link_id INTEGER、app_id TEXT。

以 visits.url=urls.id 关联，每次 visit 独立事件；不能按 URL 合并入库。
visit_time 是自 1601-01-01 UTC 起的微秒，使用整数 timedelta，避免先除成浮点损失精度。
visit_duration 按 Chromium 微秒语义处理；本次未对照 UI 验证时长，M3 复核。
transition 保留原始整数（含标志位）。相同时间的多次访问应使用 `(visit_time, id)` cursor
或重叠查询 + 稳定 visit id 去重，不能仅使用 `visit_time > last_time`。
不同浏览器/Profile 的 visit id 可冲突，source_id 必须包含浏览器与 Profile。

临时复制主库与存在的 `-wal`，连接副本；不在原库上 checkpoint 或写入。
`-shm` 可由副本连接重建。活动数据库的多文件复制非原子操作，失败时重试且不推进 cursor。
本次真实 Chrome 无 WAL；带 WAL 的读取只在 M0 合成测试验证，M3 需补真实运行验收。

## Safari / Arc（待本机验证）

Safari History.db 的复制被 macOS 完全磁盘访问权限阻止，**没有实际读出其字段**。
按实施计划暂定 history_items 与 history_visits 关联，visit_time 从 2001-01-01 UTC 起以秒计。
`safari_unverified.sql` 是最小假定 schema，授权后必须更新，不能视作兼容性保证。
Safari 的标题可能位于 visits；访问时长和 transition 不应伪造为 Chromium 字段。

Arc 计划路径为 `~/Library/Application Support/Arc/User Data/{Default,Profile *}/History`。
尚未安装，暂用 `arc_unverified.sql` 记录最小 Chromium 假定；M3 检查实际列后再适配。

## Git（M2 待实现）

M0 只检查本机 git 可执行文件及默认作者邮箱是否存在，没有采集任何真实 commit。
计划输出中 %aI 是作者时间；用时间 cursor 处理 --all、迟到旧提交和分支切换时要防漏采。
作者邮箱需精确匹配，避免把 git --author 的正则模糊匹配当成邮箱相等。
仓库根目录与 hash 组成来源标识；是否跨克隆合并同一 hash 在 M2 明确。
二进制 numstat 会出现 `-`，文件名可能含换行，解析时必须考虑 NUL 分隔。

## 手动收藏 / OCR（M4 待实现）

M0 未向浏览器发送 Apple 事件、未截图、未编译 OCR。
Chrome/Safari JavaScript 开关与自动化授权必须在真实 Hammerspoon 调用路径下测试。
AppleScript 正文来自 document.body.innerText；知乎“展开阅读全文”等未展开内容可能取不到，
PDF / 页面脚本失败应降级为截图 + OCR，记录经过脱敏的 page_text_error。
Swift Vision 的 bbox 原点在左下，阅读顺序需转换；OCR 不等于对截图像素做了脱敏。
截图原图只存在本机 data_dir；所有派生文本必须先脱敏再落库或写 Markdown。

## M0 的边界

这里只完成脚手架、配置/建表、诊断和格式研究；没有采集器、快捷键或定时任务。
doctor 的 ✅ 只代表对应检查已实测；⚠️ 代表未验证，⚪ 代表未发现可选应用。
当前 Codex 进程能读到的文件不代表终端、Hammerspoon 或 launchd 都能读到。
M0 默认 doctor 在诊断完成后退出 0；`--strict` 检测到 ❌ 返回 1，配置/运行失败返回 2。
