# 框架：从个人轨迹编译 (workflow, verifier)

这份文档把提案里的五步方法细化到可以实现的程度，并说明每一步在代码里的位置。
相对提案有三处改动，先列在前面：

1. **输入以已有的访问记录为主，录屏降为可选。** 主要来源是 coding agent 对话日志（Claude Code、Codex，本机与服务器）、
   shell 历史、浏览器历史、导出的聊天记录、最近打开的文件、git。它们本来就在机器上，不需要用户改变习惯去录制，
   其中对话日志是最密的验收信号（理由见 [related-work.md](related-work.md) §7）。所有来源写进同一种事件格式。
2. **verifier 从两层变成三层。** 在“客观正确性”和“任务偏好”之间加了一层跨任务的**个人验收风格**，
   并且除了“查什么”（条目）还记录“怎么查”（policy：查多深、何时查、默认信任还是怀疑、失败后怎么办）。
   前者决定产出过不过，后者决定执行 skill 的 agent 该怎么工作。
3. **“理解”这一步全部交给别人的 coding agent。** 本项目自己不调任何模型 API。它做三件事：
   确定性地采集与压缩轨迹；把任务写成规格，在 Claude Code / Codex 里开无头会话去执行；
   用确定性的检查把会话产出卡住（lint、verifier 冻结校验、预算账本）。

## 总览

```
 采集 ─────────────► 编译 ──────────► 蒸馏（agent 会话）──────────► 闭环
 sources/            compile/         distill.py + prompts/          loop.py

 agent   对话日志     spans            会话 A  profile                lint      verifier 与本人留下/丢弃的版本是否一致
 shell   命令历史     signals   ───►    ├ profile/profile.md          optimize  冻结 verifier，在 workflow 空间里搜
 browser 浏览历史     day.md            ├ acceptance-style.yaml       shadow    与人并行跑，对比差异
 wx      聊天导出                       └ tasks.yaml                  feedback  本人的接受/拒绝 → 新的带标签样例
 recent  最近文件                      会话 B×N  每个任务一个          evolve    提出 verifier 修改
 git     提交记录                       └ skills/<name>/              approve   本人批准后才生效
 timelog 时间日志                          SKILL.md  verifier.yaml    install   拷进 ~/.claude/skills 或 ~/.codex/skills
 (可选) 录屏 / 视频                        checks/   cases/  evidence.md
```

数据全部在一个目录下（默认 `data/`，可用 `HT2WV_HOME` 改），可以整个查看和删除。

## ① 采集：一种事件格式，多个来源

**先授权，再读取。** `ht2wv setup` 打开本机问卷页面（[setup_ui.py](../ht2wv/setup_ui.py)）：用户先添加并测试服务器连接，
再逐项勾选来源，最后一键启动采集 → 编译 → 蒸馏。决定存在 `consent.yaml`，未决定等同于不允许；
发现阶段只检查路径或主机是否存在，不打开数据（[consent.py](../ht2wv/consent.py)）。
录屏是可选的：只靠访问记录就能跑完整条管线，只是屏幕类信号（核对、撤销、返工）拿不到，verifier 主要来自对话类信号。

每个来源都往 `traces/<day>/events.jsonl` 追加 `{t, src, k, ...}`。事件种类见 [store.py](../ht2wv/store.py) 顶部。

| 来源 | 命令 | 记什么 | 不记什么 |
|---|---|---|---|
| agent 对话 | `ht2wv collect agents` | 用户每条消息、agent 每轮最后的回复与用过的工具、用户中断、用户拒绝的工具调用 | 工具输出、思考过程、系统注入的消息 |
| 浏览器 | `ht2wv collect browser` | 访问时间、标题、URL 的 host 加 path | query string（常带 token 和搜索词） |
| 聊天导出 | `ht2wv collect chat <导出文件> --me <昵称>` | 时间、对方、是否本人、文本 | **不读微信的本地加密数据库**；只接受用户自己导出的 csv / jsonl / txt |
| 时间日志 | `ht2wv collect timelog x.csv` | ManicTime / ActivityWatch 一类的导出 → 窗口区间 | |
| git | 授权后自动 | 从 agent 对话的工作目录向上找到的仓库：提交时间、标题、文件列表 | diff |
| 本机 shell 历史 | 授权后自动 | PowerShell / bash / zsh 历史，脱敏 | |
| 服务器 shell 历史 | 授权后自动 | 经密钥 ssh 只读 `~/.bash_history`、`~/.zsh_history` 末尾若干行。没有时间戳的历史只保留顺序，标 `undated` | 密码；终端软件保存的会话 |
| 服务器 agent 对话 | 授权后自动 | 经 ssh 打包拉回 `~/.claude`、`~/.codex` 近几天的会话日志，按本机日志同样解析 | |
| 最近打开的文件 | 授权后自动 | Windows“最近使用”里的文件名与时间 | 文件内容 |
| 工作目录 | 授权后自动 | 指定目录下文档类文件的文件名与修改时间 | 文件内容 |
| 显式标注 | `ht2wv mark "刚才那版数字抄错了"` | 用户随手记一句 | |
| 实时录屏（可选） | `ht2wv record` | 前台窗口切换、打字**次数**与退格数、快捷键组合、点击与滚动次数、剪贴板（长度、哈希、脱敏后的前 120 字）、被监视目录里的文件保存（小文件按内容哈希留版本）、触发式截图 | 按键内容；命中 denylist 的窗口（密码管理器、无痕窗口、网银）只留应用名 |
| 录屏视频（可选） | `ht2wv collect video x.mp4` | 每 2 秒采样，感知哈希去重后的关键帧 | 没有键鼠事件，所以屏幕类信号检测不到，只能靠 agent 看帧 |

以下两段只与可选的录屏有关。截图是“按需”的：窗口切换后、保存或发送类快捷键后、以及每分钟一次，且与上一张的感知哈希差异足够大才留。
结构化事件优先于像素（提案 §5 的隐私取舍）。所有文本入库前过一遍脱敏（密钥、JWT、口令、卡号、身份证、邮箱、手机号）。

**文件版本是关键设计。** 被监视目录里的小文件每次保存都按哈希存一份到 `blobs/`。
这样“保存 → 离开 → 回来改”就留下了一对文件：前一版是这个人自己不满意的，后一版是他留下的。
这是不需要任何标注就能得到的 reject / accept 样例，verifier 的一致率就在它们上面算。

## ② 编译：确定性地把一天压成 agent 能读的东西

[compile/](../ht2wv/compile/__init__.py) 不调模型，产出两个文件：

- `signals.jsonl`：主线之外的行为候选。
- `day.md`：按小时分段的时间线，窗口区间、对话、访问、提交、文件保存合并排序，信号以 `⚑` 行内嵌，截图给出路径。

检测器（[signals.py](../ht2wv/compile/signals.py)）故意做得简单、召回优先，每个命中只是“候选加指针”，含义留给 agent 判断：

对话类信号（`spec` 往下）只需要访问记录；屏幕类信号（`crosscheck` 到 `version_churn`）需要开启可选的录屏。

| 信号 | 规则 | 它可能说明什么 |
|---|---|---|
| `crosscheck` | A → B → A，在 B 停留不超过 60 秒、没打字、没复制东西回来 | 在拿 B 核对 A：B 是他认的事实来源 |
| `lookup` | 同上但从 B 复制并粘贴回 A | 主线（取数），不是核对。区分这两者是整个检测的要点 |
| `undo_burst` | 15 秒内连续两次以上 Ctrl+Z | 对刚做的东西不满意 |
| `paste_fix` | 粘贴后 45 秒内大量删除或撤销 | 粘来的内容需要手工修 |
| `ai_paste` | 剪贴板来自 AI 应用；按粘贴后的行为分 accepted / edited / rejected | 他对 AI 产出的接受度，以及改了多少 |
| `pre_commit_review` | 保存或发送前有一段只滚动不打字的时间 | 交付前通读，时长反映检查深度 |
| `hesitation` | 发送前长时间无输入 | 对发出去这件事谨慎 |
| `rework` | 同一文件保存后离开，过 1 分钟到 2 小时又改了且内容不同 | 前一版不合格；给出 rejected / kept 两个版本的哈希 |
| `version_churn` | 同目录下 `x`、`x_v2`、`x_final` | 反复修改的产出 |
| `spec` | 用户写给 agent 的长消息里有“硬性约束 / 必须停下 / 产出 / 预算”等 | 他自己写下来的验收标准，`source: stated` |
| `correction` | agent 回复后的下一条消息命中否定类词表 | 打回；被打回的产出就是上一条回复 |
| `verify_request` | 命中“确定吗 / 核对 / 跑一下 / 来源”等 | 默认不信任，要证据 |
| `acceptance` | 短消息以“可以 / 好 / ok”开头 | 通过；与 correction 的比例和延迟反映验收节奏 |
| `abort` / `deny` | 中断、拒绝工具调用 | 风险边界 |
| `respec` | 其余的后续消息 | 补充要求 |

传统 task mining 把这些当噪声删掉；这里它们单独成表，是 verifier 的原料。

## ③ 蒸馏：在别人的 agent 里开会话

[distill.py](../ht2wv/distill.py) 开两类会话，每个会话的任务书都按“产出 / 硬性约束 / 必须停下 / 自检”的格式写
（[prompts/](../ht2wv/prompts/)），渲染后的全文存进 `sessions/<时间>-<种类>/TASK.md`，可以审计，也可以手工重发。

**会话 A：画像与任务清单**（[profile.md](../ht2wv/prompts/profile.md)）。读若干天的轨迹，写三个文件：

- `profile/profile.md`：**工作习惯**（怎么给 agent 下任务、怎么拆、何时设检查点、卡住怎么办、何时自己动手）与
  **验收风格**（查多深、何时查、默认信任还是怀疑、要什么证据、最常为什么打回、对什么零容忍）。每条跟证据。
- `profile/acceptance-style.yaml`：验收风格的机器可读版，见下。
- `profile/tasks.yaml`：识别出的任务，含出现记录、变量与不变量、相关信号、打分。

**会话 B：每个任务一个**（[skill.md](../ht2wv/prompts/skill.md)），可并行。产出 `skills/<name>/`：

- `SKILL.md`：标准 Agent Skill。步骤写“目标、输入输出、判断条件”，不重放点击；能走接口和文件就不操作界面。
  **工作习惯落在这里**：这个人在哪一步停下来核对，步骤里就在哪一步设检查点。
- `verifier.yaml` 加 `checks/*.py`：见下。
- `cases/`：从 `blobs/` 还原的历史样例，带 accept / reject 标签。
- `evidence.md`：每条标准的证据链、别的解释、以及**没写进去**的候选标准。

会话 B 必须跑通 `python -m ht2wv lint <name>` 才算完成。这是“verifier 的 verifier”：
结构合法；个人条目都有证据；本人留下的版本不能被检查脚本判失败；本人丢弃的版本必须有东西能判它失败。

### verifier 的形状

```yaml
skill: weekly-report
version: 1
kind: [writing, data]
accept_threshold: 0.8
inherits: ../../profile/acceptance-style.yaml      # 个人层，跨 skill 共享
policy:                                            # 怎么查（工作习惯与验收风格在这里生效）
  check_depth: full          # spot | full
  timing: both               # incremental | final | both
  trust_default: verify      # trust | verify
  on_fail: fix_then_recheck  # 或 stop_and_ask
  max_fix_rounds: 2
  evidence_required: [数据来源文件名]
  escalate_when: [源数据缺失, 数字与上周相差超过一个量级]
  risk_tolerance: low
items:                                             # 查什么
  - id: O1
    layer: objective         # 客观层：与人无关，可共享，缓解冷启动
    claim: 报告里每个数字都等于源表里的值
    how: check
    check: checks/o1_numbers.py
    weight: 3
    hard: true               # 不过就直接拒绝，不看总分
    source: observed
    evidence: ["2026-01-05:S002", "2026-01-05:S003"]
  - id: P1
    layer: preference        # 任务偏好层：这个人在这个任务上特有的
    claim: 只列数字，不写评价性的话
    how: judge
    rubric: 出现“表现亮眼 / 稳步增长”一类无数字支撑的评价即不通过
    weight: 1
    confidence: 0.7
    source: corrected
    evidence: ["2026-01-05:S013"]
```

三层：

| 层 | 范围 | 例子 | 来源 |
|---|---|---|---|
| `objective` | 与人无关 | 数字对得上、文件齐全、没发错对象 | 任务本身；可跨人共享 |
| `style` | 这个人，跨任务 | 结论要附来源；不接受没跑过的“已完成”；不要形容词 | `acceptance-style.yaml`，按 `applies_to` 标签继承 |
| `preference` | 这个人，这个任务 | 周报只列三条数字、末尾写数据文件名 | 该任务的信号 |

每条都有 `source`（`stated` 明说的 / `corrected` 从打回里看出的 / `observed` 从本人行为里看出的 / `hypothesized` 猜的）、
`confidence` 和 `evidence`。没有证据的个人条目只能是 `hypothesized`、置信度不超过 0.3、不能是 hard——lint 会拦。

判定：能写成脚本的写成 `check`（退出前打印 `{"pass":..., "detail":...}`），写不成的才是 `judge`（带 rubric，由独立的评审会话判）。
任一 hard 条目失败即拒绝；否则按权重算通过比例，与阈值比。未判定的条目不计入分母并单独列出。

`verifier.yaml` 是给人看、给人改的。[verifier.py](../ht2wv/verifier.py) 只依赖标准库和 pyyaml，安装 skill 时被拷成 `verify.py`，
skill 在 Claude Code / Codex 里执行时自己就能跑验收，不需要装本项目。

### workflow 以多会话 prompt 交付，verifier 是共用的那一份

skill 目录里除了 `SKILL.md` 还有 `stages/NN-<名字>.md`（2 到 4 个），每个文件是交给一个独立 coding agent 会话的完整 prompt。
执行时（[loop.py](../ht2wv/loop.py) 的 `execute`）按顺序每个 stage 开一个会话，会话之间不共享记忆，只靠沙盒里 `work/` 的文件交接。
`verifier.yaml` 被渲染成一份 `VERIFIER.md`（条目、rubric、policy），原样附在**每一个**会话的 prompt 后面：
流程可以拆成任意多段，但“怎样算做对”只有一份定义。最后一个会话负责跑 `verify.py` 并修到通过。

## ④ 闭环优化：固定 verifier，搜 workflow

`ht2wv optimize <skill>`（[loop.py](../ht2wv/loop.py)）：

1. 取有输入的历史样例，按输入去重后分成 train / val。
2. 每个样例开一个**执行会话**：沙盒里只有导出的 skill 和 `input/`，看不到本人当时的产出。
3. verifier 打分：检查脚本直接跑；judge 条目开一个独立的**评审会话**，按 `policy` 的深度查。
4. 开一个**改进会话**：读 train 上的逐条失败，只允许改 `SKILL.md`。
5. 在 val 上重跑；不比之前差才保留，否则回滚。

三条防线，对应的是“优化器会去优化目标函数本身”这个老问题：
verifier、检查脚本、样例在改进前后做哈希比对，变了整轮作废；改进会话看不到 val；
任务书明确禁止把样例答案写进 workflow 或教执行者绕过检查。

## ⑤ 影子运行与反馈：verifier 只经由本人更新

- `ht2wv shadow <skill> --input <dir> [--human <dir>]`：跑一遍并打分。给了本人的实际产出时，再开一个**对比会话**，
  把差异分成 `workflow_gap`（verifier 已经抓到，流程的问题）、`verifier_gap`（verifier 放过了，但本人版本明显在遵循某个标准）和 `noise`，
  后者附建议条目，存进 `skills/<name>/proposals/`。
- `ht2wv feedback <run> accept|reject --note ...`：本人的裁决。这次运行变成一个带标签的新样例，同时记下 verifier 当时判了什么。
- `ht2wv evolve <skill>`：开一个会话，读反馈与提案，找 verifier 与本人不一致的地方，写出 `verifier.proposed.yaml` 和逐条理由。
- `ht2wv approve <skill>`：提案过 lint 后替换现行版本，旧版本归档。**没有这一步，verifier 不会变。**

verifier 是目标函数，所以它的修改权只在本人手里；agent 能提案，不能生效。

## 评估（对应提案 §4）

`ht2wv eval <skill>` 给出：

| 提案的问题 | 这里的量 |
|---|---|
| verifier 学得像不像 | `agreement`：带标签样例上 verifier 结论与本人标签的一致率，并列出误放与误拒 |
| workflow 做得好不好 | `acceptance_curve`：历次运行中本人直接接受的累计比例 |
| 是否越用越准 | 同一条曲线随反馈次数的走向；`verifier_vs_person_on_runs` |
| 耦合是否必要 | `ht2wv eval <skill> --verifier <别人的或通用的 verifier.yaml>`：换一个 verifier 后，它与**本人**标签的一致率掉多少 |

第四项目前只做了一半：能量出“别人的 verifier 判本人的样例有多不准”，
还没有自动化“用别人的 verifier 优化出 workflow，再看本人接不接受”这条完整对照，需要第二个人的数据。

## 没做的

- 实时录屏只支持 Windows；没有读界面结构（UI Automation）和浏览器当前 URL，窗口标题之外的语义靠截图。
- 任务切分完全交给 agent，没有与 TMI 那样的专门方法对比。
- 触发：skill 装进 agent 后靠 description 被动触发；没有“检测到这个人开始做某任务就主动影子运行”。
- 多人、组织级流程不在范围内（与提案一致）。
