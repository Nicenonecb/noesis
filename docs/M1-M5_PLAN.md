# NOESIS · 求是：M1–M5 详细开发计划

> 本文档用来细化《第一期实施计划》里的 M1–M5，交给 Codex 执行。
> 项目已改名：代码在 `~/code/noesis`，包名和命令都是 `noesis`，数据目录是 `~/NOESIS`。
> **以 M0 已经提交的代码和 `docs/FORMAT_NOTES.md` 为准**。本文档里的字段名、表名如果和 M0 实际情况冲突，以实际为准，同时在汇报里说明。

---

## 0. 总览

### 0.1 排期与依赖

| 里程碑   | 内容                                                         | 依赖  | 工作量 |
| -------- | ------------------------------------------------------------ | ----- | ------ |
| **M1.0** | 公共层补强：写入接口、查询层、FTS5、会话表、运行记录、并发锁 | M0    | M      |
| **M1.1** | Claude Code 采集                                             | M1.0  | M      |
| **M1.2** | Codex 采集                                                   | M1.0  | M      |
| **M2**   | Git 采集 + 仓库发现 + 项目名统一                             | M1    | M      |
| **M3**   | 浏览器历史（Chrome / Arc / Safari）                          | M1.0  | M      |
| **M4**   | ⌥⌘S 快捷键收藏（截图 + OCR + 网页正文 + 备注）               | M1.0  | L      |
| **M5**   | 每日日志 + launchd 定时任务 + 脱敏审计                       | M1–M4 | M      |

M2、M3、M4 互不依赖，但**仍按顺序做，每做完一个停下来汇报**。

### 0.2 每个里程碑交付时都要有

1. 单独的 commit（可以拆成多个），提交前 `pytest` 全部通过
2. 一份汇报，写在 `docs/reports/Mx.md`，内容包括：做了什么；验收标准逐条的 ✅/❌ 和验证方法（贴上命令和输出摘要）；已知问题；需要我手动做的事
3. 如果更新了 `docs/FORMAT_NOTES.md`，在汇报里说明改了什么

---

## 1. 跨里程碑的公共约定（M1.0 实现）

M1.0 不对应任何数据源，但后面所有采集器和以后的前端都要用到，所以先做。

### 1.1 采集器接口

```python
# noesis/collectors/base.py
@dataclass
class CollectResult:
    source: str
    inserted: int
    skipped: int       # 已经存在（幂等跳过）
    warnings: int
    errors: list[str]

class Collector(Protocol):
    name: str                                   # "claude_code" / "codex" / ...
    def collect(self, ctx: Context, *, backfill: timedelta | None = None,
                dry_run: bool = False) -> CollectResult: ...
```

- `ctx` 里有 config、db 连接、logger、时区
- 采集器**不直接写 SQL**，只调用 `db.py` 里的函数
- 每处理 500 条，在**一个事务里**同时写入事件和更新 cursor。这样中途崩溃也不会出现"数据写了一半、cursor 已经前移"

### 1.2 `db.py` 写入接口

```python
upsert_events(conn, events: Iterable[Event]) -> tuple[int, int]   # (inserted, skipped)
    # INSERT ... ON CONFLICT(id) DO NOTHING
update_event_meta(conn, event_id, patch: dict)                    # 用 json_patch 局部更新 meta
upsert_session(conn, session: Session)
get_cursor(conn, source, key) -> str | None
set_cursor(conn, source, key, value)
```

### 1.3 新增表（用 `PRAGMA user_version` 做迁移，迁移脚本放 `noesis/migrations/`）

**`sessions`**：CC/Codex 会话的汇总，前端和日志都要用

| 字段                      | 说明                                               |
| ------------------------- | -------------------------------------------------- |
| `id` TEXT PK              | `sha1(source + "|" + session_id)`                  |
| `source`                  | `claude_code` / `codex`                            |
| `session_id`              | 原始会话 id                                        |
| `project`                 | 项目名                                             |
| `cwd`                     | 工作目录                                           |
| `title`                   | CC 的 summary 行，没有就取第一条用户消息的前 60 字 |
| `started_at` / `ended_at` | UTC                                                |
| `n_user` / `n_assistant`  | 消息数                                             |
| `raw_path`                | 原始文件路径                                       |

**`ingest_runs`**：每次采集的运行记录（`noesis stats` 和以后的前端"健康状态"都用它）
`id, source, started_at, finished_at, status(ok|partial|failed), inserted, skipped, warnings, error`

**`events_fts`**：全文索引

```sql
CREATE VIRTUAL TABLE events_fts USING fts5(
  title, content, url,
  content='events', content_rowid='rowid',
  tokenize='trigram'
);
-- 再加 INSERT / UPDATE / DELETE 三个触发器，让索引和 events 表保持同步
```

- 用 `trigram` 分词器是因为 SQLite 默认分词不会切中文。trigram 能搜任意 **3 个字及以上**的中文子串
- **少于 3 个字的查询**改用 `LIKE` 兜底，在 `search()` 函数内部处理，调用方不需要关心
- `trigram` 要求 SQLite ≥ 3.34。`noesis doctor` 要检查 `sqlite3.sqlite_version`

### 1.4 查询层（给日志渲染、CLI、以后的 API 共用）

放在 `noesis/queries.py`，**禁止在 CLI 和渲染代码里直接写 SQL**：

```python
get_events(conn, *, start, end, sources=None, kinds=None, projects=None,
           limit=None, offset=0) -> list[Event]
get_sessions(conn, *, start, end, source=None) -> list[Session]
get_session_events(conn, session_id) -> list[Event]
get_captures(conn, *, start, end) -> list[Event]
search(conn, q, *, limit=50, sources=None) -> list[SearchHit]   # 带高亮片段
domain_summary(conn, *, start, end) -> list[DomainStat]
project_time(conn, *, start, end) -> list[ProjectTime]           # 算法见 M5
stats(conn) -> Stats
```

所有 `start` / `end` 参数都用**带时区的 datetime**。"某一天"一律按 config 里的时区换算成 UTC 区间，有一个公共函数 `day_range(date, tz)`。

### 1.5 其他公共规则

- **并发锁**：`collect`、`build-daily` 执行前先拿文件锁 `~/NOESIS/run/collect.lock`（用 `fcntl.flock`）。拿不到就打一行日志退出，退出码 0，避免手动运行和 launchd 同时跑
- **时间**：入库一律是 UTC ISO8601（带 `Z`），渲染时再转本地时区。用标准库 `zoneinfo`
- **日志**：写到 `~/NOESIS/logs/noesis-YYYY-MM-DD.log`；warning 计入 `ingest_runs.warnings`
- **容错**：单条记录解析失败 → warning + 跳过；单个文件失败 → warning + 继续下一个；整个数据源失败 → 记 `status=failed`，不影响其他数据源
- **内容截断**：截断时在末尾加 `…[truncated N chars]`，meta 里写 `truncated: true`
- **项目名解析**：统一用 `resolve_project(cwd) -> str` 函数。M1 先返回 cwd 的最后一级目录名，M2 再升级成"所在 git 仓库的根目录名"

### 1.6 M1.0 验收

- [ ] 迁移脚本能在 M0 已有的数据库上跑，也能在空库上跑；重复跑不报错
- [ ] `search()` 能搜到 3 个字和 2 个字的中文、英文单词，有测试覆盖
- [ ] 两个 `noesis collect` 同时启动，第二个会因为拿不到锁而直接退出
- [ ] 查询层每个函数都有单元测试（用内存数据库加假数据）

---

## 2. M1：Claude Code + Codex 采集

### M1.1 Claude Code（`noesis/collectors/claude_code.py`）

#### 文件发现

- 扫描 `~/.claude/projects/*/*.jsonl`
- 子 agent 的文件放在哪里、`isSidechain` 怎么标记，**以 FORMAT_NOTES 为准**。`skip_sidechain=true` 时整份跳过
- 每个文件对应一个 cursor：`key=文件绝对路径`，`value=JSON{offset, size, inode, mtime}`

#### 增量读取

1. 打开文件，`seek(offset)` 后往下读
2. **只处理以 `\n` 结尾的完整行**。最后一行如果没写完（CC 正在写），就留到下次读，offset 停在这一行开头
3. 如果 `inode` 变了，或者文件比 offset 还短 → 当作文件被重写，从头读一遍，靠 id 去重
4. 如果 `mtime` 和 `size` 都没变 → 直接跳过，不打开文件

#### 解析规则

| 行类型                                               | 处理                                                         |
| ---------------------------------------------------- | ------------------------------------------------------------ |
| `type=user`，content 是字符串                        | → `user_msg`                                                 |
| `type=user`，content 是 block 数组                   | 只拼接 `text` block；只有 `tool_result` 的行**整行跳过**；`image` block 只在 `meta.images` 里计数，不存 base64 |
| `isMeta == true`                                     | 跳过                                                         |
| 系统注入的文本                                       | 去掉 `<system-reminder>…</system-reminder>` 这类块后，如果剩下的是空的 → 跳过。要去掉的标签做成配置项 `claude_code.strip_tags`，默认值根据 FORMAT_NOTES 调研结果来填 |
| 斜杠命令（`<command-name>/xxx</command-name>` 这类） | → `user_msg`，`content` 存命令本身，`meta.is_command=true`   |
| `[Request interrupted by user]` 这类                 | 跳过                                                         |
| `type=assistant`                                     | 只取 `text` block；`tool_use` 写进 `meta.tools`（只存 `{name, 关键参数摘要}`，比如 `Edit noesis/db.py`）；`thinking` 不存 |
| **同一个 `message.id` 拆成了多行**（流式输出时常见） | **合并成一条 `assistant_msg`**，`ts` 取第一行的时间，文本和 tools 按顺序拼起来 |
| `type=summary`                                       | 不生成事件，用来更新 `sessions.title`                        |
| 其他类型                                             | 计入 `meta.skipped_types` 统计，不报 warning                 |

- `source_id`：user 消息用 `uuid`，assistant 消息用 `message.id`（没有的话用第一行的 `uuid`）
- `project = resolve_project(cwd)`；`meta` 里存 `cwd`、`git_branch`、`model`
- AI 回复按 `max_assistant_chars` 截断；`raw_ref = 文件路径:起始行号`
- 每读完一个文件，upsert 对应的 `sessions` 记录

### M1.2 Codex（`noesis/collectors/codex.py`）

#### 文件发现

- `~/.codex/sessions/**/rollout-*.jsonl`（按 `YYYY/MM/DD` 分目录）
- `~/.codex/history.jsonl`
- cursor 的做法和 CC 一样（按文件记 offset/inode/size/mtime）

#### 解析规则（**写之前先对照 FORMAT_NOTES 确认；新旧版本格式都要兼容**）

| 内容                              | 处理                                                         |
| --------------------------------- | ------------------------------------------------------------ |
| `session_meta`                    | 取 `id`、`cwd`、`timestamp`、`cli_version` → `sessions` 表   |
| 用户输入                          | **优先**用 `event_msg` 里 `type=user_message` 的文本（这是用户真正输入的内容）；如果这个版本没有这种行，就退回 `response_item` 里 `role=user` 的消息，并过滤注入内容 |
| 要过滤的注入内容                  | 以 `<environment_context>`、`<user_instructions>`、`# AGENTS.md instructions`、`<permissions instructions>` 等开头的块。这些前缀做成配置项 `codex.injected_prefixes`，默认值按调研结果填 |
| AI 回复                           | `response_item` 里 `role=assistant` 的 `output_text`；没有的话退回 `event_msg` 的 `agent_message`。**两者都有时只取一份** |
| `reasoning`                       | 不存                                                         |
| `function_call` / 本地 shell 调用 | 写进上一条 assistant 消息的 `meta.tools`（存命令摘要，最多 200 字） |
| 无法识别的结构                    | warning + 跳过                                               |

- `source_id = sha1(session_id + ts + role + text[:200])`，因为 Codex 的行没有自带唯一 id
- `history.jsonl` 的用途：如果某条输入**在会话文件里找不到对应消息**（比如会话文件已被删掉），就补一条 `user_msg`，标 `meta.from_history=true`。判断"是否对应"的方法是：同一个 session_id 下，时间相差 ≤ 5 秒且文本前 100 字相同

### M1.3 CLI

```
noesis collect [--source claude_code|codex|...] [--backfill 7d|30d|all] [--dry-run]
noesis stats
```

- `--backfill`：**忽略 cursor**，把 mtime 落在时间窗口内的文件全部重读，按 `ts` 过滤，靠 id 去重。跑完后把 cursor 更新到文件末尾
- `--dry-run`：只解析、只统计，不写库，打印每个数据源会新增多少条
- `stats` 输出：每个数据源的事件总数、今天新增数、最近一次运行的时间和状态、最近的 warning 数

### M1 测试

- `tests/fixtures/claude_code/`：**改写过的假数据**，要覆盖：纯文本 user、带 tool_result 的 user、isMeta、system-reminder 注入、斜杠命令、一条 assistant 拆成 3 行、thinking、tool_use、summary、sidechain、最后一行没写完
- `tests/fixtures/codex/`：新格式和旧格式各一份，要覆盖：环境注入、AGENTS.md 注入、event_msg 和 response_item 重复、reasoning、function_call、history 里有但会话文件里没有的输入
- 必须有的测试：
  - [ ] 用户消息里不含任何 tool_result 和注入内容
  - [ ] 多行 assistant 被合并成一条
  - [ ] 连续跑两次，第二次 `inserted=0`
  - [ ] 写到一半的行这次不处理，下次读到完整后能入库
  - [ ] 文件被重写后能正确重读、不产生重复
  - [ ] 截断标记正确

### M1 验收（用真实数据，汇报里贴结果）

- [ ] `noesis collect --source claude_code --backfill 7d` 和 `--source codex --backfill 7d` 都能跑通，`stats` 里有数据
- [ ] **随机抽 5 条用户消息、5 条 AI 回复**，和原始 jsonl 逐条比对，内容一致（汇报里只写比对结果，**不要贴我的真实对话内容**）
- [ ] 在真实数据里搜 `tool_result`、`<system-reminder>`、`<environment_context>`，在 user_msg 里出现的次数为 0
- [ ] 连续跑两次，事件数不变
- [ ] 全量回填（`--backfill all`）的耗时和事件数写进汇报
- [ ] `sessions` 表里的会话数和磁盘上的会话文件数基本对得上（有差异要解释原因）

---

## 3. M2：Git 采集（`noesis/collectors/git_log.py`）

### 3.1 新增表 `repos`

`path TEXT PK（realpath）, name, common_dir, discovered_via(config|scan|session), first_seen, last_seen, enabled INTEGER`

### 3.2 仓库发现（每次 collect 时先跑一遍，结果写进 `repos`）

1. config 里的 `git.repos`
2. 扫描 `git.scan_roots`，最多 3 层，**跳过** `node_modules`、`.venv`、`venv`、`Library`、`.cache`、`dist`、`build` 和隐藏目录（`.git` 本身除外）
3. `sessions` 表里所有 `cwd` → `git -C <cwd> rev-parse --show-toplevel`，cwd 已经不存在的跳过
4. 用 `git rev-parse --git-common-dir` 去重，**同一个仓库的多个 worktree 只算一个**
5. CLI 命令：`noesis repos list | add <path> | disable <path>`

### 3.3 作者过滤

- 邮箱集合 = config 里的 `author_emails` ∪ 全局 `git config user.email` ∪ 每个仓库自己的 `user.email`
- 传参：`--author=<email1> --author=<email2>`（git 对多个 `--author` 取"或"）

### 3.4 读取

```
git -C <repo> log --all --date-order --since=<cursor - 1 天>
    --author=... --pretty=format:'%H%x1f%aI%x1f%cI%x1f%an%x1f%ae%x1f%P%x1f%D%x1f%s%x1f%b%x1e'
    --numstat
```

- cursor 记录的是这个仓库已见过的**最大 committer date**。往回多读 1 天，防止 rebase 或时间乱序漏掉提交，多出来的靠 hash 去重
- `ts` 用 author date（`%aI`），也就是真正写代码的时间
- 解析 numstat 时，二进制文件显示为 `-\t-`，按 0 行计
- merge commit（`%P` 里有多个父提交）：入库，`meta.is_merge=true`，日志里默认不显示
- 每个仓库超时 15 秒；失败就 warning，继续下一个
- `source_id = commit hash`；`project = 仓库目录名`；`session_id = 仓库名`
- `meta`：`repo`、`repo_path`、`refs`、`is_merge`、`files_changed`、`insertions`、`deletions`、`files`（最多 50 个）
- **不存 diff 内容**

### 3.5 统一项目名

- `resolve_project(cwd)` 升级为：cwd 在某个已知仓库里 → 返回仓库名；否则返回 cwd 的最后一级目录名
- 新增 `noesis reproject`：用新规则重算已有 CC/Codex 事件和 sessions 的 `project` 字段
- 目的：同一个项目在 CC、Codex、Git 里的名字必须一致，比如 CC 在 `redbear-crm/scripts` 里聊的，也要归到 `redbear-crm`

### 3.6 M2 测试

- 用 `git init` 在临时目录里生成假仓库：两个作者、merge、二进制文件、worktree、rebase 改过时间的提交
- [ ] 只采到指定作者的提交
- [ ] 主仓库和 worktree 只算一次
- [ ] 重复跑不会重复入库
- [ ] numstat 统计正确

### 3.7 M2 验收

- [ ] `noesis repos list` 能列出我最近在 CC/Codex 里操作过的仓库（汇报里列出仓库名和发现途径）
- [ ] 任选 2 个仓库，最近 7 天的提交数和 `git log --author=我 --since=7.days --all` 一致
- [ ] `reproject` 跑完后，CC、Codex、Git 三个来源的项目名能对上（列出前 10 个项目和各自的事件数）

---

## 4. M3：浏览器历史（`noesis/collectors/browser_history.py`）

### 4.1 支持哪些浏览器（做成配置项，方便以后加 Edge、Brave）

```toml
[[browser.profiles_glob]]
name = "chrome"
glob = "~/Library/Application Support/Google/Chrome/{Default,Profile *}/History"
kind = "chromium"
[[browser.profiles_glob]]
name = "arc"
glob = "~/Library/Application Support/Arc/User Data/{Default,Profile *}/History"
kind = "chromium"
[[browser.profiles_glob]]
name = "safari"
glob = "~/Library/Safari/History.db"
kind = "safari"
```

不存在的路径直接跳过，不报 warning。

### 4.2 安全地读数据库

1. 把 `History` 和同目录下的 `History-wal`、`History-journal`（存在的话）一起复制到临时目录
2. 用只读方式打开：`sqlite3.connect("file:...?mode=ro", uri=True)`
3. 读完删掉临时目录（用 `try/finally`）
4. **任何时候都不能直接打开浏览器正在用的原文件**

### 4.3 Chromium（Chrome / Arc）

```sql
SELECT v.id, v.visit_time, v.transition, v.visit_duration, v.from_visit,
       u.url, u.title
FROM visits v JOIN urls u ON u.id = v.url
WHERE v.visit_time > :cursor_time
ORDER BY v.visit_time
```

- 时间换算：`unix = visit_time / 1e6 - 11644473600`
- `visit_duration` 单位是微秒，换成秒存进 meta
- `transition & 0xFF` 是跳转类型：**丢弃** `AUTO_SUBFRAME (3)` 和 `MANUAL_SUBFRAME (4)`；其余的把类型名（link、typed、reload 等）存进 `meta.transition`
- cursor：每个 profile 记一个 `max(visit_time)`
- `source_id = f"{browser}:{profile}:{visit_id}:{visit_time}"`（加上时间，是为了防止历史被清空后 id 从头开始导致冲突）

### 4.4 Safari

```sql
SELECT hv.id, hv.visit_time, hv.title, hi.url
FROM history_visits hv JOIN history_items hi ON hi.id = hv.history_item
WHERE hv.visit_time > :cursor_time
```

- 时间换算：`unix = visit_time + 978307200`
- 读取失败（没有"完全磁盘访问权限"）→ 本数据源记 `status=failed`，`doctor` 里提示怎么授权，**不影响其他浏览器**

### 4.5 清洗

- **丢弃**：`chrome://`、`arc://`、`about:`、`file://`、`data:`、`blob:`、`chrome-extension://`、`localhost`、`127.0.0.1`
- **黑名单**：用 `fnmatch` 匹配主机名（`blacklist_domains`）；另外支持 `blacklist_url_regex`
- **URL 脱敏**：查询参数里的 `token`、`access_token`、`code`、`key`、`sig`、`signature`、`password`、`session` 等，值替换成 `REDACTED`
- **URL 归一化**：去掉 `utm_*`、`fbclid`、`gclid`、`spm`、`from`、`share_*` 这类追踪参数，结果存进 `url`；原始 URL（已脱敏）存进 `meta.url_raw`
- **域名**：`meta.domain` 存小写的主机名，去掉开头的 `www.`
- **去重合并**：同一个浏览器 profile 里，**60 秒内连续访问同一个 URL**（刷新、重定向）只保留第一条，`meta.repeat` 记合并了几次
- `content = title`（这一期不存网页正文）；`title` 为空时用 URL 的路径部分代替

### 4.6 M3 测试

- 造一个假的 Chromium History 库和一个假的 Safari History.db（按真实的表结构，字段可以精简）
- [ ] 时间换算正确（用已知时间点断言）
- [ ] 子框架访问被丢弃
- [ ] 黑名单和 URL 脱敏生效
- [ ] 追踪参数被去掉
- [ ] 60 秒内的重复访问被合并
- [ ] 文件被锁住的情况下，复制后照样能读

### 4.7 M3 验收

- [ ] 本机装了的浏览器都能读到（汇报里列出：浏览器 / profile / 事件数）
- [ ] **浏览器开着的时候**跑 collect，正常不报错
- [ ] 抽 3 条访问记录，时间和浏览器"历史记录"页面显示的一致
- [ ] 配置一个黑名单域名，访问后再采集，确认没有入库
- [ ] Safari 没授权时有明确提示；授权后能读到

---

## 5. M4：⌥⌘S 快捷键收藏

### 5.1 组件

| 文件                               | 作用                                                         |
| ---------------------------------- | ------------------------------------------------------------ |
| `noesis/capture/ocr/ocr.swift`     | Vision OCR，编译成 `~/NOESIS/bin/noesis-ocr`                 |
| `noesis/capture/browser_bridge.py` | 用 osascript 读浏览器的网址、标题、正文、选中文字            |
| `noesis/capture/capture.py`        | `noesis capture` 主流程                                      |
| `noesis/capture/render.py`         | 从数据库生成单条收藏的 md（**md 文件每次都从数据库重新生成，不做局部修改**） |
| `hammerspoon/noesis.lua`           | 快捷键、备注弹窗、通知                                       |

### 5.2 时序（目标：按下快捷键后 ≤ 1.5 秒弹出备注框）

```
Hammerspoon 收到 ⌥⌘S
 ├─ 记下 win:id()、app:bundleID()
 ├─ 同步执行（用绝对路径调用）: noesis capture --window-id N --app BUNDLE
 │     1. screencapture -x -o -l N <png>              ← 必须最先做
 │        失败时（窗口已经关掉、没有权限）退回整屏截图 screencapture -x <png>
 │     2. 如果是浏览器 → browser_bridge（超时 3 秒）
 │     3. 写入 events：source=capture, importance=high, meta.ocr_status=pending
 │     4. 生成 md
 │     5. 在后台启动 OCR 进程：noesis capture-ocr <id>（不等它结束）
 │     6. stdout 输出 JSON {"id":..., "title":...}
 ├─ hs.dialog.textPrompt("为什么存这个？")   ← 截图已经完成，不会把弹窗截进去
 ├─ 填了备注 → noesis annotate <id> --note "..."
 └─ hs.notify："已收藏：<标题>"
后台：noesis capture-ocr <id>
       → 跑 noesis-ocr → 脱敏 → update_event_meta + 更新 content → 重新生成 md
```

- **OCR 和备注会同时改同一条记录**。所以两边都只用 `update_event_meta` 局部更新各自的字段，然后各自从数据库重新生成 md，这样不会互相覆盖
- 再加一个快捷键 **⌥⌘⇧S**：用 `screencapture -i` 手动框选区域（用来截长图里的某一段、视频里的某一帧等），后面的流程一样

### 5.3 browser_bridge 要读哪些东西

注入下面这段 JS，返回一个 JSON 字符串：

```js
(() => {
  const pick = document.querySelector(
    'article, main, .Post-RichText, .RichContent-inner, .QuestionAnswer-content');
  const root = pick || document.body;
  return JSON.stringify({
    url: location.href,
    title: document.title,
    selection: String(window.getSelection() || ''),
    text: root.innerText.slice(0, MAX),
    text_root: pick ? pick.className || pick.tagName : 'body',
    description: document.querySelector('meta[name=description]')?.content || '',
    lang: document.documentElement.lang || ''
  });
})()
```

- 先找正文容器，是为了尽量去掉知乎侧边栏、推荐列表这些噪音；找不到就用整个 body
- 各浏览器怎么执行 JS：
  - Chrome：`tell application "Google Chrome" to execute active tab of front window javascript "…"`
  - Arc：`tell application "Arc" to tell front window to tell active tab to execute javascript "…"`
  - Safari：`tell application "Safari" to do JavaScript "…" in current tab of front window`
- 浏览器的 bundle id：`com.google.Chrome`、`company.thebrowser.Browser`、`com.apple.Safari`
- **降级顺序**：JS 执行成功 → 全部信息都有；JS 被禁止 → 只用 AppleScript 读网址和标题（`URL of active tab`），并记 `meta.page_text_error="js_disabled"`；连这个都失败 → 只有截图和 OCR

### 5.4 OCR 小工具

- `noesis-ocr <png>` → stdout 输出 `{"text": "...", "lines": [{"text","bbox":[x,y,w,h],"confidence"}], "ms": 123}`
- `VNRecognizeTextRequest`：`recognitionLevel = .accurate`，`recognitionLanguages = ["zh-Hans","en-US"]`，`usesLanguageCorrection = true`
- 阅读顺序：先按行的 y 坐标分组（容差是行高的一半），每行内部再按 x 坐标排
- 由 `scripts/install.sh` 用 `swiftc -O` 编译；`doctor` 检查这个二进制在不在、能不能运行

### 5.5 数据

- 文件：`~/NOESIS/captures/YYYY-MM/<id>.png` 和 `<id>.md`，`id = YYYYMMDD-HHMMSS-<4 位随机>`（防止一秒内连按两次重名）
- `events`：`kind=capture`，`title` 用网页标题（没有的话用"App 名 + 窗口标题"），`url`，`content` = 选中文字 + 正文 + OCR 文本（**全部脱敏后**拼接，按 `max_page_chars` 截断）
- `meta`：`app_bundle`、`window_title`、`screenshot`（相对路径）、`selection`、`page_text_len`、`text_root`、`ocr_status(pending|done|failed)`、`ocr_ms`、`note`、`page_text_error`
- md 的格式按《第一期实施计划》第 6 节，图片用 Obsidian 的 `![[...]]` 嵌入

### 5.6 出错时怎么处理

| 情况                      | 行为                                                         |
| ------------------------- | ------------------------------------------------------------ |
| 没有屏幕录制权限          | 截出来是空白或者只有壁纸 → 检测图片是否几乎全是同一种颜色，是的话通知"请授权屏幕录制" |
| 窗口 id 失效              | 退回整屏截图                                                 |
| 浏览器 JS 被禁止          | 按 5.3 降级，通知里加一句"正文未获取，可以在浏览器设置里打开 JS 权限" |
| OCR 失败                  | `ocr_status=failed`，收藏仍然保留                            |
| `noesis capture` 整体失败 | Hammerspoon 通知显示错误摘要，日志里有详细信息               |
| 1 秒内连按两次            | 第二次直接忽略（在 Hammerspoon 里做防抖）                    |

### 5.7 M4 测试

- `browser_bridge`：把 osascript 的调用 mock 掉，测试三种降级路径
- `capture`：把 screencapture 和 OCR mock 掉，测试入库、md 生成、OCR 和 annotate 先后到达时的结果一致
- `noesis-ocr`：放一张中英混排的测试图（自己生成的，不能用真实截图），断言能识别出几个关键词

### 5.8 M4 验收（我会手动测，Codex 先准备好测试清单）

- [ ] 知乎回答页按 ⌥⌘S → **1.5 秒内**弹出备注框 → 提交后收到通知
- [ ] 生成的 md 里有网址、标题、正文（不是整页导航）、OCR 文本、备注；在 Obsidian 里能看到截图
- [ ] 先选中一段文字再按，`selection` 里就是那段文字
- [ ] 在微信、预览、终端里按，能存下截图和 OCR
- [ ] 关掉 Chrome 的 JS 权限后再按，降级正常，通知有提示
- [ ] ⌥⌘⇧S 框选区域截图可以用
- [ ] 连按两次只产生一条记录

---

## 6. M5：每日日志 + 定时任务 + 脱敏审计

### 6.1 `noesis build-daily`

```
noesis build-daily [--date YYYY-MM-DD|today|yesterday] [--catch-up 7]
```

- `--catch-up N`：检查最近 N 天，**日志文件不存在，或者当天有比文件更新的事件**，就重新生成
- 只通过查询层取数据；输出写到 `~/NOESIS/daily/YYYY-MM-DD.md`
- **输出是确定的**：同样的数据库内容，生成的文件逐字节相同。不能有"生成时间"这类每次都会变的内容，生成时间放到 frontmatter 之外的日志文件里。这样才能做快照测试

### 6.2 日志结构（在《第一期实施计划》第 8 节的基础上细化）

```markdown
---
date: 2026-10-22
type: daily
sources: {claude_code: 83, codex: 40, git: 4, browser: 120, capture: 3}
projects: [redbear-crm, red-bear-game, noesis]
---
# 2026-10-22 活动日志

## 概览
（各数据源数量；项目投入时长排行，最多 8 个）

## ⭐ 手动收藏
（按时间排；每条：时间、标题、域名、备注、摘录、到收藏 md 的链接）

## 按项目
### redbear-crm · 约 2h30m
#### Claude Code · 14:02–15:40 · 《会话标题》
- 👤 14:02 第一条消息（单行，最多 120 字）
- 🤖 回复摘要（单行，最多 300 字）`[tools: Read×3, Edit×1]`
- …（每个会话最多显示 20 轮，多出来的写"…另有 N 轮"）
#### Codex · …
#### Git
- 15:42 `a1b2c3d` fix: lock question ordering（+42/−7，3 个文件）

### （其他项目……）

## 未归类
（没有 project 的会话）

## 浏览（按域名）
| 域名 | 次数 | 停留 | 代表页面（最多 3 个） |
```

- **按项目组织**，而不是按数据源，这样一眼就能看出一个项目今天发生了什么。M6 的 AI 提炼也更好接
- 摘录统一处理成单行：换行替换成 ` ⏎ `，\`\`\` 替换成 `ʼʼʼ`，防止 Markdown 结构被打乱
- 链接都用相对于 `~/NOESIS` 的 Obsidian 链接

### 6.3 项目投入时长怎么算（`queries.project_time`）

1. 取当天这个项目的全部事件（CC、Codex、Git、收藏，**浏览记录不算**，因为它没有 project），按时间排序
2. 相邻两个事件间隔 ≤ 15 分钟就算连续，把间隔时间计入；间隔 > 15 分钟就当作断开
3. 每段连续活动再加 2 分钟（覆盖第一个事件之前的时间）
4. 结果四舍五入到 5 分钟，写成"约 Xh Ym"
5. 算法写进 docstring，并有单元测试

### 6.4 launchd

| Label                       | 触发方式                               | 执行                                                |
| --------------------------- | -------------------------------------- | --------------------------------------------------- |
| `com.justin.noesis.collect` | `StartInterval 1800`，`RunAtLoad true` | `noesis collect`                                    |
| `com.justin.noesis.daily`   | `StartCalendarInterval` 23:30          | `noesis collect && noesis build-daily --catch-up 7` |

- `ProgramArguments` 用 venv 里 `noesis` 的**绝对路径**
- 设置 `EnvironmentVariables.PATH`，要包含 `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`，不然 launchd 环境里找不到 git
- `StandardOutPath` / `StandardErrorPath` 指向 `~/NOESIS/logs/launchd-*.log`
- 如果 23:30 时 Mac 在睡眠，launchd 会在唤醒后补跑；`--catch-up 7` 负责补上漏掉的天数
- `scripts/install.sh`：创建 venv 并安装依赖 → 编译 OCR → 生成 plist（替换绝对路径）→ `launchctl bootout` 旧任务（忽略错误）→ `launchctl bootstrap gui/$(id -u)` → 链接 Hammerspoon 配置。**重复运行结果相同**
- `scripts/uninstall.sh`：卸载 launchd 任务、移除 Hammerspoon 链接，**不删数据**
- `doctor` 新增检查：launchd 任务是否已加载、上次退出码；输出 launchd 实际使用的 python **真实路径**（对 venv 的 python 做 `realpath`），我要把"完全磁盘访问权限"授权给这个路径

### 6.5 脱敏审计

- 新命令 `noesis audit-redaction [--fix]`：用 `redact.py` 的全部规则扫描整个 `events` 表和 `daily/`、`captures/` 下的所有 md，报告命中数量和位置（只报位置，不打印命中的内容）
- `--fix`：对命中的记录重新脱敏，再重新生成受影响的 md
- **端到端测试**：在 CC、Codex、浏览器 URL、收藏正文的 fixture 里各埋 2 个假 key → 走完整条流程（collect → build-daily）→ `audit-redaction` 结果为 0，并且对输出目录 `grep` 假 key 原文，也找不到

### 6.6 M5 测试

- 快照测试：固定的 fixture 数据库 → 生成的日志和 `tests/snapshots/daily.md` 完全一致
- `project_time` 的边界情况：只有一个事件、间隔正好 15 分钟、跨午夜
- `--catch-up` 只重新生成需要更新的那几天

### 6.7 M5 验收

- [ ] 用真实数据生成最近 3 天的日志，在 Obsidian 里打开：结构清楚，截图和链接都能点开（汇报里只描述结构，不贴真实内容）
- [ ] 跑完 `install.sh` 后，`launchctl print gui/$(id -u)/com.justin.noesis.collect` 显示已加载；放一晚，第二天日志自动生成
- [ ] 第二次运行 `install.sh` 不报错、不产生重复任务
- [ ] 端到端脱敏测试通过；对真实数据跑 `audit-redaction` 的结果写进汇报
- [ ] `doctor` 全部是 ✅，或者 ❌ 项都附了明确的修复步骤

---

## 7. 需要我手动做的事（Codex 汇总成清单给我，按里程碑分组）

| 时机 | 事项                                                         |
| ---- | ------------------------------------------------------------ |
| M3   | 给 launchd 用的 python 真实路径授权"完全磁盘访问权限"（为了读 Safari） |
| M4   | 安装 Hammerspoon；给它授权"辅助功能"和"屏幕录制"             |
| M4   | 第一次截图时，允许 Hammerspoon 控制 Chrome / Arc / Safari（系统会弹窗） |
| M4   | Chrome：菜单「显示 → 开发者 → 允许 Apple 事件中的 JavaScript」；Safari：「开发 → 允许 Apple 事件中的 JavaScript」；Arc 类似 |
| M5   | 运行 `scripts/install.sh`；用 Obsidian 打开 `~/NOESIS` 作为库 |

---

## 8. 给 Codex 的工作约定（补充第一期计划第 13 节）

1. 每次只做一个里程碑（M1 可以先做 M1.0，汇报后再做 M1.1 和 M1.2），做完停下来等我确认
2. **汇报里不能贴我的真实对话、浏览记录、截图内容**，只写数量、结构和比对结果
3. 真实格式和本文档不一致时，以真实为准，更新 FORMAT_NOTES，在汇报里说明
4. 查询逻辑只能写在 `queries.py`，为 M7 的前端 API 做准备
5. 除了 M6，任何代码都不能发起网络请求