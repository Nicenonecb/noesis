# NOESIS · 求是

**从实事中求是，让每一次循环都进到高一级**

在本机采集个人活动，统一成 SQLite 事件，并在后续里程碑生成 Markdown 日志。
代码位于 `~/Desktop/noesis`，数据位于 `~/NOESIS`；运行时代码只使用 Python 标准库。

**M1–M5 已实现。** 本地采集 Claude Code / Codex 对话、Git 提交和浏览历史，
支持中文搜索、截图收藏、Vision OCR 与按项目组织的每日日志。
Python 运行时只用标准库；截图、OCR、快捷键和定时任务依赖 macOS。
M6 AI 提炼与 M7 前端不在本次范围，应用运行时不发起网络请求。

阶段验收、修复过的 bug 和待人工验证项见 [交付总览](docs/reports/DELIVERY.md)。
快捷键需要安装并授权 Hammerspoon；Safari 需要完全磁盘访问权限。

## 命名说明

“求是”取意于“实事求是”。毛泽东在《改造我们的学习》（1941 年 5 月 19 日）中解释：

> “实事”就是客观存在着的一切事物，“是”就是客观事物的内部联系，即规律性，“求”就是我们去研究。

——[《改造我们的学习》原文，第三节](https://www.marxists.org/chinese/maozedong/marxist.org-chinese-mao-19410519.htm)

对 NOESIS 而言，本机活动记录是研究的材料；整理、核对和关联这些材料，是形成认识的过程。
每一项判断都应能回到证据，并在后续行动中接受检验与修正。
“从实事中求是，让每一次循环都进到高一级”是本项目的标语，表达从记录到认识、
再以行动结果改进认识的方向，不作为上述原文的逐字引述。

## 处理流程

长期处理流程的四个阶段依次命名为：**去粗取精 → 去伪存真 → 由此及彼 → 由表及里**。

| 阶段 | 在 NOESIS 中的含义 |
|---|---|
| 去粗取精 | 清理重复与噪声，提取有用的活动内容，整理为统一结构，并保留来源线索。 |
| 去伪存真 | 核对来源、时间与上下文，区分真实用户输入、系统注入和工具输出；分清记录事实、模型推断与待核实内容。 |
| 由此及彼 | 沿会话、项目和时间建立材料之间的联系，把分散事件串成可回溯的上下文。 |
| 由表及里 | 在证据基础上提炼决策、经验和未解决的问题，再用后续行动结果检验与修正认识。 |

四个阶段是处理理念，不替代 M0–M6 的实施顺序。第一期先建立可靠的采集与整理基础；
跨事件推理、长期记忆和主动提醒仍属于后续规划。当前完成了 M0–M1，
尚未启用完整的四阶段处理流水线。

## 本机使用

```sh
cd ~/Desktop/noesis
source .venv/bin/activate
noesis init
noesis doctor
noesis collect
noesis stats
noesis search "数据库"
noesis search "索引" --source codex --limit 20
```

数据默认位于 `~/NOESIS`；可通过 `--data-dir` 或 `NOESIS_DATA_DIR` 指定其他目录。
数据目录不能放进代码仓库。用 Obsidian 打开该目录作为库即可浏览 Markdown 和截图。

```sh
noesis collect --source claude_code --backfill 7d
noesis collect --source codex --backfill all --dry-run
noesis collect --source git
noesis collect --source browser_history
noesis collect --replay
noesis repos list
noesis repos add /绝对路径/仓库
noesis repos disable /绝对路径/仓库
noesis reproject
noesis build-daily --date yesterday
noesis build-daily --catch-up 7
noesis daily-run --catch-up 7
noesis audit-redaction
noesis audit-redaction --fix
```

`--backfill` 忽略旧游标并回填指定窗口，`--replay` 重读对话但保留其正常游标。
`--dry-run` 在内存数据库副本上执行解析与去重，不修改持久化数据或运行日志。
首次普通采集可能导入来源的全部历史；可先用带时间窗口的 dry-run 查看数量。
`stats` 的今天新增按入库时间统计。

退出码 0 表示完成或被并发锁跳过，1 表示部分来源失败或审计有未处理命中，2 表示配置或运行错误。
`daily-run` 即使部分来源失败也生成日志，并通过退出码保留失败状态。

## 截图收藏

安装集成后，在 Hammerspoon 中重载配置：

- `⌥⌘S` 收藏当前窗口；`⌥⌘⇧S` 框选区域。
- 截图完成后弹出备注框，网页正文与 OCR 在后台补齐。
- 收藏保存到 `captures/YYYY-MM/`，包括 PNG 和 Markdown。
- Chrome / Arc / Safari 可以读取正文、标题、URL 与选中文字；其他应用使用截图和 OCR。
- 失败的 OCR 可以通过 `noesis capture-ocr <收藏ID>` 重试。
- `noesis annotate <收藏ID> --note "备注"` 修改备注并重新生成 Markdown。

系统设置中为 Hammerspoon 授予辅助功能、屏幕录制和浏览器自动化权限。
浏览器还需开启“允许 Apple 事件中的 JavaScript”。未安装 Hammerspoon 时，命令行仍可使用。

## 安装与卸载后台集成

```sh
scripts/install.sh
scripts/uninstall.sh
```

安装脚本离线创建或复用虚拟环境、安装本地项目、编译 OCR、生成两个 launchd 任务，
并把 Hammerspoon 模块链接到本机配置。重复安装不会追加重复任务或重复 require。
依赖不在本机缓存时停止，不自动联网下载。Hammerspoon 应用需自行安装。
已有用户 init.lua 会保留并在首次修改前备份；同名非 NOESIS 模块冲突时不会覆盖。

- 每 30 分钟采集一次，加载任务时也采集。
- Mac 系统时区的每天 23:30 采集并补生成最近 7 天日志。
- 睡眠后由 launchd 在唤醒时补触发；开机及睡眠补触发仍须实机长期验收。
- 卸载仅移除任务和本工具的 Hammerspoon 加载配置，保留数据。

`doctor` 显示 launchd 加载状态、上次退出码和真实 Python 路径。
Safari 授权应以该真实路径及实际启动应用为准；当前进程权限不能代表后台任务权限。
定时任务日志位于 `~/NOESIS/logs/launchd-*.log`。

## 数据与隐私边界

- SQLite schema v3 保留 M0 的事件身份、UTC 微秒时间格式及哈希游标键。
- 每 500 条完整对话源记录一起提交事件和游标；失败回滚当前批，已提交批次保留。
- 前缀指纹检查支持同长度重写，仍需读取旧文件字节。重写不自动删除历史归档。
- Claude Code 同 message.id 的分块合并；用户消息排除工具结果和注入，推理不保存。
- Codex 按出现次数配对多通道镜像，history 用同会话、前 100 字及 ±5 秒匹配。
- Git 以共同仓库目录去重 worktree，只收集配置及本机 Git 邮箱集合的提交，不存 diff。
- 浏览器仅查询临时数据库副本。普通历史不保存网页正文，主动收藏才提取正文。
- 敏感文本在入库前脱敏，搜索索引随数据同步；短中文搜索自动使用 LIKE。
- 脱敏是模式匹配，无法识别所有自由文本秘密，也不处理截图像素。
- 每日日志和收藏 Markdown 是生成文件，手工编辑可能被后续重建覆盖。
- 项目时长根据事件间隔估算，并非精确工时；单事件按计划取整可能显示 0 分钟。

## 开发验证

```sh
.venv/bin/python -m pytest -q
```

fixtures 为合成数据；macOS 上的 OCR 测试会实际编译 Swift 并识别合成中英图片。
每个阶段单独提交，写后审查规则见 AGENTS.md，报告位于 docs/reports/。
未安装浏览器、未授权系统权限和需要隔夜观察的验收不会被标记为自动通过。
