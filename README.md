# NOESIS · 求是

**从实事中求是，让每一次循环都进到高一级**

在本机采集个人活动，统一成 SQLite 事件，并在后续里程碑生成 Markdown 日志。
代码位于 `~/Desktop/noesis`，数据位于 `~/NOESIS`；运行时代码只使用 Python 标准库。

**当前仅完成 M0。** 可用命令是 `init`、`doctor`。其他模块为后续里程碑预留，
不会采集对话、历史记录、截图，不会安装快捷键/定时任务，也不会发起网络请求。

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
跨事件推理、长期记忆和主动提醒仍属于后续规划。当前仅完成 M0，本文新增命名说明，
尚未启用四阶段处理流水线。

## 本机使用

本机已创建 Python 3.11 虚拟环境，项目和 pytest 都通过本机缓存离线安装。

```sh
cd ~/Desktop/noesis
source .venv/bin/activate
noesis init
noesis doctor
python -m pytest
```

不激活环境也可直接执行 `~/Desktop/noesis/.venv/bin/noesis`。
本阶段没有修改 shell 配置或创建全局命令链接。

已有本地缓存的环境可重建：

```sh
uv venv --offline --python /opt/homebrew/bin/python3.11 .venv
uv pip install --offline --python .venv/bin/python setuptools pytest
uv pip install --offline --no-build-isolation --python .venv/bin/python -e .
```

缓存不全时应停止并说明缺失依赖，不自动联网安装。

## 配置和诊断

`init` 创建 config.toml、goals.yaml 模板、私有数据子目录、events/cursors 表和索引。
重复运行保留配置、目标与事件。数据目录支持 `--data-dir /绝对路径` 或 NOESIS_DATA_DIR；
自定义目录中的 config.toml.data_dir 必须与其所在目录一致，不允许存放在本代码仓库内。

`doctor` 检查路径、当前解释器、表结构、真实历史库副本和工具可用性。
它不弹系统权限框、不启动浏览器、不采集数据。默认“诊断完成”返回 0；
`doctor --strict` 有 ❌ 时返回 1，配置/运行错误返回 2。⚠️ 表示需要手动验证，不能视为已授权。

本机 Safari 读取被拒绝，Arc 与 Hammerspoon 未检测到。手动事项集中在
`docs/M0_REPORT.md`，实际格式与尚未验证的假设见 `docs/FORMAT_NOTES.md`。

## 持久化与隐私

Event 将时间规范为 UTC、用 sha1(source + "|" + source_id) 去重，capture 强制 high。
Database 的写入接口统一脱敏正文、标题、URL、raw_ref、metadata 及 cursor 值；
cursor.key 存原始逻辑键的 SHA-256，避免带秘密的路径在替换后发生键碰撞；
调用方须在同一事务内写事件与 cursor。脱敏是模式匹配，无法保证识别所有自由文本中的秘密，
也不会处理截图像素。日志或 Markdown 的后续写入必须复用脱敏模块，先脱敏后截断。

fixture 全部合成；仓库忽略 SQLite、截图目录、日志、运行配置、bin 及虚拟环境。
M6 之前不引入网络代码；M6 可选且必须经用户确认后才能执行。

## 里程碑

| 里程碑 | 状态 |
|---|---|
| M0 脚手架、init/doctor、格式调研 | 已实现，验收结果见 M0_REPORT |
| M1 Claude Code / Codex 增量采集 | 等待用户确认后开始 |
| M2 Git | 待实现 |
| M3 浏览历史 | 待实现，Safari 需授权后补格式验证 |
| M4 快捷键收藏 / OCR | 待实现 |
| M5 日志 / launchd | 待实现 |
| M6 AI 每日提炼 | 可选，未启用 |

每个里程碑测试通过后单独 commit，汇报并等待用户确认。
