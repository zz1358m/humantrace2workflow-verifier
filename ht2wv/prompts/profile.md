# TASK：从电脑使用轨迹中蒸馏这个人的工作画像与任务清单

工作目录就是数据根目录。你要读的轨迹在 `traces/<day>/`，本次范围：{{days}}。

每天的目录里有：
- `day.md`：时间线摘要（从这里开始读）。`⚑` 行是启发式检测出的“主线之外”的行为候选，不是结论。
- `signals.jsonl`：`⚑` 行的完整字段。`events.jsonl`：全部原始事件。
- `shots/`：截图或视频关键帧，只有开了录屏才有（用 Read 直接看图；只看时间线让你有疑问的那些，不要逐张看）。
- `blobs/`：被追踪文件的历史版本，按 sha 命名。

事件来源可能包括：Claude Code / Codex 对话日志（本机与服务器）、shell 命令历史、浏览器历史、导出的聊天记录、最近打开的文件、git、时间日志，以及可选的屏幕录制与录屏视频。
哪些来源存在取决于用户开了什么，缺了就按有的做，不要臆测缺失来源里的内容。

数据根目录下如果有 `request.md`，那是本人写下的目的和 rubric，算 `stated` 证据（引用写 `request:<id>`），
`tasks.yaml` 里必须有一个任务对应它，且排在第一位。如果有 `workdir/`，那是他工作目录的快照。

这是一个无人值守任务。**不要停下来等确认**。

## 产出

1. `profile/profile.md`：给人读的画像，两部分：
   - **工作习惯**：这个人怎么推进工作。例如怎样给 agent 下任务（一句话还是写完整的规格）、
     任务怎么拆、先做什么后做什么、什么时候设检查点、偏好的工具与信息源、并行还是串行、
     卡住时怎么办、什么时候自己动手而不是交给 agent。
   - **验收风格**：这个人怎么判断“做对了”。例如查得多深（抽查还是全查）、什么时候查
     （边做边查还是最后查）、默认信任还是默认怀疑、要不要证据（来源、截图、测试结果）、
     最常为了什么打回、对什么零容忍、对什么无所谓、风险容忍度（宁可慢也不能错，还是先发再改）、
     表达不满的方式。
   - **汇报风格**：这个人希望别人（包括 agent）怎么向他汇报结果。例如结论放最前还是最后、要一句话还是要细节、
     表格还是段落、要不要过程叙述、数字带不带单位和精度、例外情况怎么标、多长算太长、哪些词他反感。
     证据来自他怎么打回 agent 的总结（“太长”“先说结论”“别讲过程”）、他自己发给别人的汇报长什么样、他追问了什么（说明汇报里缺了什么）。
   - **做事顺序**：哪些事他坚持先做、哪些事必须等另一件事确认后才做、哪些动作他从不让 agent 代劳。
   每一条都要跟证据：`<day>:<signal id>` 或 `<day> HH:MM:SS` 加一句原话或行为描述。
2. `profile/acceptance-style.yaml`：上面“验收风格”的机器可读版，是所有 skill 的 verifier 都会继承的个人层。格式：
   ```yaml
   policy:            # 这个人怎么查，执行 skill 的 agent 要照着做
     check_depth: spot | full
     timing: incremental | final | both
     trust_default: trust | verify
     on_fail: fix_then_recheck | stop_and_ask
     max_fix_rounds: 2
     evidence_required: [..]        # 交付时必须附带的东西
     escalate_when: [..]            # 遇到什么必须停下问人
     risk_tolerance: low | medium | high
   items:             # 跨任务通用的验收条目
     - id: ST1
       claim: 一句可判定的话
       how: judge
       rubric: 评审时具体看什么，什么算不通过
       layer: style                 # 或 report：汇报风格与可读性的条目用 report
       applies_to: ["*"]            # 或任务类型标签，如 ["writing", "code", "data", "research"]
       weight: 1
       hard: false
       confidence: 0.0-1.0
       source: observed | stated | corrected | hypothesized
       evidence: ["2026-10-12:S014"]
   ```
3. `profile/tasks.yaml`：从轨迹里识别出的、值得做成 skill 的任务：
   ```yaml
   tasks:
     - name: kebab-case-英文名
       title: 一句话说明
       kind: [writing | code | data | research | comms | ops ...]
       intent: 这个人做这件事是为了什么
       occurrences: [{day, t0, t1, note}]
       variables: 每次不同的东西（输入）
       invariants: 每次相同的东西（流程骨架）
       signals: 与它相关的 signal id 列表（verifier 的原料）
       has_artifacts: true/false     # blobs/ 里有没有它的输入或产出版本
       score: 0-10                   # 重复度 × 信号密度 × 可自动化程度
       why: 打分理由
   ```

## 硬性约束

1. 只写 `profile/` 下的这三个文件。不改 `traces/`，不读数据根目录之外的任何东西。
2. 每一条画像和验收条目都必须有轨迹证据。没有证据但你认为合理的，标 `source: hypothesized`、
   `confidence ≤ 0.3`、`hard: false`。**宁可少写，不要编**。
3. `source` 的含义：`stated` 是这个人明说过的要求；`corrected` 是从他打回或修改里看出来的；
   `observed` 是从他自己的行为（核对、返工、撤销）里看出来的。
4. 区分主线和主线之外：复制数据粘贴过来是流程的一部分；看一眼别处什么都没改又回来，是在核对。
   后者才是验收标准的证据。
5. 纠正的含义要读上下文判断。追问不一定是否定，“不对”之后的那句话才是标准本身。
6. 已有 `profile/` 文件时是更新而不是重写：保留仍成立的条目，有新证据就追加并上调 confidence，
   被新证据反驳的降 confidence 并写明。
7. 不要把任何密钥、口令、身份证号、他人隐私写进产出。轨迹里的 `[EMAIL]` `[KEY]` 等占位符保持原样。
8. 任务不设数量上限，但 score < 4 的不必列。只出现过一次、但这个人为它写了完整规格的任务也算。

## 做法建议

先通读各天的 `day.md`，再按 kind 用 Grep 扫 `signals.jsonl`
（`correction`、`verify_request`、`abort`、`deny`、`spec`、`crosscheck`、`rework`、`ai_paste`、`pre_commit_review`）。
对话类 signal 的 `quote` 只有开头一段，要看全文就按 session id 到 `events.jsonl` 里找。
画像要具体到能据此预测他下一次会打回什么；“注重质量”这种话没有用。

## 结束时

最后一条消息只写：写了哪些文件、识别出几个任务（按 score 排序列出名字）、哪些结论证据偏弱。
