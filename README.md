# NOESIS · 求是

**从实事中求是，让每一次循环都进到高一级。**

NOESIS 是面向 macOS 的个人活动记录工具，将散落在对话、代码提交和浏览记录中的工作线索，
整理成可搜索、可回溯的本地日志。数据保存为 SQLite 和 Markdown，可以用 Obsidian 浏览、关联和复盘。

## 能做什么

| 能力 | 说明 |
|---|---|
| 对话归档 | 增量采集 Claude Code 与 Codex 的本机会话，去重并保留来源线索。 |
| 代码记录 | 采集 Git 提交，按仓库和项目统一组织，支持 worktree 去重。 |
| 浏览历史 | 采集 Chrome、Arc、Safari 历史，支持过滤和连续访问合并。 |
| 截图收藏 | 快捷键收藏窗口或区域，补充备注、网页正文和本地 Vision OCR。 |
| 中文搜索 | 按关键词检索记录，可限定来源与返回数量。 |
| 每日日志 | 按项目生成 Markdown 日志，通过后台任务定期采集与整理。 |

采集、搜索、截图 OCR 和日志生成均在本机完成。Python 运行时无第三方依赖需要另行安装；
Markdown 解析器 Mistune 已随代码打包。

## 快速开始

需要 **Python 3.11 或更高版本**。后台任务、浏览器采集路径和截图集成面向 macOS；
截图快捷键另需 Hammerspoon，OCR 编译需要可用的 Swift 工具链。

### 1. 安装命令行工具

```sh
git clone https://github.com/Nicenonecb/noesis.git
cd noesis
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
noesis init
noesis doctor
```

请确保 `python3` 指向 Python 3.11+。安装阶段可能下载构建工具；日常运行无需再安装 Python 依赖。
默认数据目录为 `~/NOESIS`，配置文件为 `~/NOESIS/config.toml`。
可以用 `--data-dir` 或 `NOESIS_DATA_DIR` 指定其他目录，**数据目录必须位于代码仓库之外**。

### 2. 预览、采集和搜索

```sh
# 先预览最近 7 天的记录数量，不写入数据
noesis collect --backfill 7d --dry-run

# 确认后采集，再查看统计与搜索结果
noesis collect --backfill 7d
noesis stats
noesis search "数据库"
noesis search "索引" --source codex --limit 20

# 生成昨天的日志
noesis build-daily --date yesterday
```

首次直接运行 `noesis collect` 可能导入已启用来源的全部历史；之后按游标增量采集。
`--backfill` 忽略旧游标并回填指定窗口，`--dry-run` 使用内存数据库副本，不修改持久化数据或运行日志。
在配置文件的 `[sources]` 中选择采集来源，在 `[browser]` 中选择浏览器和过滤规则。

### 3. 浏览记录

用 Obsidian 打开 `~/NOESIS` 作为库，也可以直接用文本编辑器查看 Markdown。

| 路径 | 内容 |
|---|---|
| `db/noesis.sqlite` | 统一事件库与搜索索引 |
| `daily/` | 按日期生成的每日日志 |
| `captures/YYYY-MM/` | 收藏截图及对应 Markdown |
| `logs/` | 运行状态和后台任务日志 |
| `config.toml` | 数据来源、路径与运行配置 |

## 常用命令

```sh
# 按来源采集
noesis collect --source claude_code --backfill 7d
noesis collect --source codex --backfill all --dry-run
noesis collect --source git
noesis collect --source browser_history

# 管理 Git 仓库与项目归属
noesis repos list
noesis repos add /绝对路径/仓库
noesis repos disable /绝对路径/仓库
noesis reproject

# 补齐日志与检查敏感文本
noesis build-daily --catch-up 7
noesis daily-run --catch-up 7
noesis audit-redaction
noesis audit-redaction --fix
```

`noesis collect --replay` 可以重读对话并保留正常采集游标。`stats` 的“今天新增”按入库时间统计。
退出码 `0` 表示完成或被并发锁跳过，`1` 表示部分来源失败或审计有未处理命中，`2` 表示配置或运行错误。
`daily-run` 即使部分来源失败也会生成日志，并通过退出码保留失败状态。

## 截图收藏

安装下面的后台集成后，在 Hammerspoon 中重载配置：

- `⌥⌘S`：收藏当前窗口。
- `⌥⌘⇧S`：框选区域。
- 截图后填写备注，网页正文与 OCR 在后台补齐。
- Chrome、Arc、Safari 支持提取正文、标题、URL 和选中文字；其他应用使用截图和 OCR。

```sh
noesis capture-ocr <收藏ID>
noesis annotate <收藏ID> --note "备注"
```

在 macOS 系统设置中为 Hammerspoon 授予辅助功能、屏幕录制和浏览器自动化权限。
浏览器还需开启“允许 Apple 事件中的 JavaScript”。未安装 Hammerspoon 时，命令行仍可使用。
Safari 历史采集需要完全磁盘访问权限，可用 `noesis doctor` 检查实际运行路径和授权情况。

## 后台集成

```sh
scripts/install.sh

# 不再需要时卸载后台集成，保留已有数据
scripts/uninstall.sh
```

安装脚本离线创建或复用虚拟环境、安装本地项目、编译 OCR，生成 launchd 任务并配置 Hammerspoon 模块。
缺少缓存中的构建依赖时会停止，不自动联网下载；Hammerspoon 应用需自行安装。
已有 `init.lua` 会保留并在首次修改前备份，同名非 NOESIS 模块冲突时不会覆盖。

默认配置下，每 30 分钟采集一次，加载采集任务时也会运行；每天 23:30 采集并补生成最近 7 天的日志。
睡眠后的补触发由 launchd 处理，具体行为仍需在实际设备上验证。

后台运行包位于数据目录的 `bin/noesis.pyz`。修改源码后，重新运行安装脚本更新运行包。
`noesis doctor` 可查看 launchd 加载状态、上次退出码和实际执行程序；日志位于数据目录的 `logs/launchd-*.log`。
后台权限应以实际执行路径为准，当前终端权限不能代表后台任务权限。

## 数据与隐私

- 对话记录保留来源信息，排除工具结果、系统注入和推理内容；过长文本按配置截断。
- Git 只采集配置及本机 Git 邮箱集合的提交，不保存 diff。
- 浏览器历史通过临时数据库副本读取；普通历史不保存网页正文，主动收藏才提取正文。
- 敏感文本在入库前按模式脱敏，但不能识别所有自由文本秘密，也不会处理截图像素。
- 日志和收藏 Markdown 是生成文件，手工修改可能在重建时被覆盖；独立笔记应另存。
- 项目时长根据事件间隔估算，不代表精确工时。

## 为什么叫「求是」

“求是”取意于“实事求是”：以本机活动记录为材料，通过整理、核对和关联形成认识，
让判断能够回到证据，并在后续行动中检验与修正。
命名参考[《改造我们的学习》第三节](https://www.marxists.org/chinese/maozedong/marxist.org-chinese-mao-19410519.htm)。

项目用四个阶段表达长期的处理理念：**去粗取精 → 去伪存真 → 由此及彼 → 由表及里**。
当前重点是可靠的采集、搜索和每日整理，完整的四阶段处理流水线仍属于后续规划。

## 开发与验证

```sh
python -m pip install -e '.[test]'
python -m pytest -q
```

测试使用合成 fixtures；macOS 上的 OCR 测试会编译 Swift 并识别合成中英图片。
系统授权、快捷键交互和隔夜唤醒需要实机验证。

开发约定见 [AGENTS.md](AGENTS.md)，阶段验收与已知限制见[交付总览](docs/reports/DELIVERY.md)。
