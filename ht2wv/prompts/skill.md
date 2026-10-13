# TASK：把任务 `{{name}}` 编译成一个 (workflow, verifier) skill

工作目录是数据根目录。任务定义在 `profile/tasks.yaml` 的 `{{name}}` 条目里；
这个人的画像在 `profile/profile.md`，个人验收层在 `profile/acceptance-style.yaml`；
证据在 `traces/<day>/`（`day.md`、`signals.jsonl`、`events.jsonl`、`shots/`、`blobs/`）。

如果数据根目录下有 `request.md`：那是本人写下的目的和 rubric（他会逐条勾的验收清单），
属于 `stated` 证据，引用写 `request:<id>`。workflow 必须让产出满足其中每一条，verifier 必须覆盖其中每一条；
但 rubric 只是他说出口的部分，没说出口的标准要从轨迹里找。
如果有 `workdir/`：那是他工作目录的快照，可以从中取历史输入和产出来建 case（文件名带 `_v1`、`草稿` 的通常是被他改掉的版本）。

要学的不是一个流程，而是一对东西：**workflow**（怎么做）和 **verifier**（这个人认为怎样算做对）。
模型换代后 workflow 可以重写，verifier 才是要积累的资产，所以 verifier 的每一条都要站得住。

这是一个无人值守任务。**不要停下来等确认**。

## 产出：目录 `skills/{{name}}/`

1. `SKILL.md`：标准 Agent Skill（Claude Code 与 Codex 通用）。
   - frontmatter：`name: {{name}}`，`description:` 写清做什么以及**什么时候该触发**。
   - 正文按这个人自己写任务规格的习惯组织（参考 `profile/profile.md`），至少包含：
     **何时使用 / 输入 / 产出 / 硬性约束 / 必须停下的情况 / 步骤 / 交付前验收**。
   - 步骤写“目标、输入输出、判断条件”，**不要重放点击**。能走接口、命令行、文件的就走，
     只有没有别的路时才退到操作界面。把这个人每次都不变的骨架写成步骤，把每次变化的写成输入。
   - 工作习惯要落到步骤里：他在哪一步设检查点、先核对什么再继续，就照着写。
   - “交付前验收”一节固定写：运行 `python verify.py --input <输入目录> --output <产出目录>`，
     FAIL 的修掉重跑，TODO 的条目按 rubric 逐条自评并把结论写进交付说明；
     按输出里的 `policy` 行事（查多深、最多修几轮、什么情况停下问人）。
   - **workflow 以多个会话的 prompt 交付**：再写 `stages/01-<名字>.md`、`stages/02-<名字>.md` ……（2 到 4 个）。
     每个文件是交给一个独立 coding agent 会话的完整 prompt：本会话的目标、读什么、产出什么、做到什么程度算完、
     交接给下一个会话的文件（写在 `work/` 下，写明文件名和内容格式）。会话之间不共享记忆，只靠 `work/` 和 `output/` 里的文件交接。
     典型拆法：取数与核对 → 起草 → 对照验收标准审查并修正；按这个人实际的工作节奏拆，不要为了凑数硬拆。
     运行时每个会话都会自动拿到同一份验收标准（由 `verifier.yaml` 渲染成的 prompt），所以 stage 里**不要复述验收条目**，
     只写这一步怎么做；最后一个 stage 负责跑 `verify.py` 并修到通过。
   - 步骤里要引用的补充材料（字段说明、决策表之类）放在 `references/` 下，用相对链接指过去。
     执行会话只拿得到 `SKILL.md`、`stages/`、`references/`、`scripts/`、`assets/`、`checks/` 和验收标准；
     `cases/`、`evidence.md`、`CHANGELOG.md` 不会给它，引用它们等于引用一个不存在的文件。
2. `verifier.yaml`：
   ```yaml
   skill: {{name}}
   version: 1
   kind: [与 tasks.yaml 一致的标签]
   accept_threshold: 0.8
   inherits: ../../profile/acceptance-style.yaml
   policy: {}          # 只写本任务与个人默认不同的地方
   items:
     - id: O1          # objective：与人无关的客观正确性（数字对得上、文件齐全、格式能解析、没发错对象）
       layer: objective
       claim: 一句可判定的话
       how: check
       check: checks/o1_xxx.py
       weight: 3
       hard: true
       confidence: 0.9
       source: observed
       evidence: ["<day>:<signal id>"]
     - id: PR1         # process：做事的顺序与前置条件。任务有动作日志（如 output/journal.jsonl）时，
       layer: process  # 写成脚本去查日志里的先后关系：“X 之前必须有 Y”“Z 只能在最后”“同一对象不能处理两次”
       claim: ...
       how: check
       check: checks/pr1_xxx.py
       weight: 3
       hard: true
       source: corrected
       evidence: [...]
     - id: RP1         # report：汇报风格与可读性。交付汇报（output/REPORT.md）要写成这个人习惯读的样子
       layer: report   # 结构（结论在哪）、长度、表格还是段落、有没有过程叙述、数字的单位与精度、例外怎么标
       claim: ...
       how: check      # 结构性的（第一行是不是结论、行数、有没有表格、金额格式）写成脚本；
       check: checks/rp1_xxx.py   # 只有“读起来是否清楚”这种才用 judge，rubric 里写明他会嫌弃的具体写法
       weight: 2
       source: corrected
       evidence: [...]
     - id: P1          # preference：这个人在这个任务上特有的标准
       layer: preference
       claim: ...
       how: judge      # 能写成脚本就用 check，写不成才用 judge
       rubric: 评审时具体看什么；给出一个通过的例子和一个不通过的例子
       # cases: [<case id>, ...]  # 可选，仅 judge：明确列出本条预期不通过的、已存在且 label 为 reject 的样例 id
       weight: 1
       hard: false
       confidence: 0.6
       source: corrected
       evidence: [...]
   ```
   跨任务通用的个人风格条目已经通过 `inherits` 继承，**不要在这里重复**；只写本任务特有的。
3. `checks/*.py`：每个 `how: check` 的条目一个脚本。约定：
   `python checks/x.py --input DIR --output DIR`，stdout 最后一行是 `{"pass": true/false, "detail": "..."}`。
   只用标准库（确有必要可用 pyyaml）。只读 `--input` 和 `--output`，不联网，不写文件。
   detail 要具体到能照着改（哪个数字、哪一行、期望什么）。
4. `cases/<id>/`：从轨迹里还原出的历史样例，供回放和校验 verifier。
   - `input/`：当时的输入（从 `blobs/` 按 sha 拷贝，恢复原文件名）。
   - `output/`：某一版产出。
   - `case.yaml`：`label: accept | reject`，`origin:`（哪天、哪个 signal），`note:`。
   `rework` signal 给出的 `rejected_sha` / `kept_sha` 是天然的一对：前者是这个人自己不满意的版本（reject），
   后者是他留下的版本（accept）。被打回的 agent 产出同理。还原不出文件的就不建 case，不要伪造。
5. `evidence.md`：每条 verifier 条目的证据链——哪个行为或哪句话，为什么能推出这条标准，
   还有哪些别的解释、为什么排除。也写明你**没有**证据支持、因此没写进去的候选标准。

## 两类容易漏掉的标准

- **顺序**。如果任务是在一个有状态的环境里执行动作（输入里有 `env.py` 之类的工具，动作会留下日志），
  那么“先做什么后做什么”本身就是验收对象：结果碰巧对了但顺序错了，这个人不会接受。
  把他坚持的先后关系和前置条件写进 SKILL.md 的硬性约束和 stage 的拆分里，并在 verifier 里用 `process` 层的检查脚本去查日志。
  stage 的顺序就是执行顺序，拆的时候要保证前置检查所在的 stage 排在动作所在的 stage 之前。
- **汇报**。workflow 的最后一个 stage 必须写一份交付汇报 `output/REPORT.md`（除非 `request.md` 明确说不要），
  按 `profile/profile.md` 里“汇报风格”写：这个人要先看到什么、看多长、什么写法他会打回。
  verifier 里至少要有两条 `report` 层的条目（继承来的算），覆盖结构和可读性。
  汇报写得和他的习惯不一样，等于让他自己再查一遍，这在他那里就是没做完。

## 硬性约束

1. 只写 `skills/{{name}}/`。不改 `traces/`、`profile/`、其他 skill。
2. personal 条目（style / preference）必须引用证据；没有证据的标 `hypothesized`、confidence ≤ 0.3、非 hard。
3. verifier 只能依据产出本身（加上输入）来判定，不能依赖“这个人当时看了什么”这类执行时拿不到的信息。
4. verifier 不能迁就 workflow：不要因为某条标准难以满足就删掉或放宽。
5. `cases/*/output` 里 label 为 accept 的版本不得被用来反推并硬编码进检查脚本（例如把正确答案写死）。
   检查脚本必须从 `--input` 推出期望值。
6. 不要把密钥、口令、他人隐私写进任何产出。

## 自检（必须通过才算完成）

运行 `python -m ht2wv lint {{name}}`。它会检查结构，并在每个 case 上跑 verifier，
要求 accept 的 case 不被判 reject 且没有失败的检查；reject 的 case 至少有一条检查脚本不通过，
或有 judge 条目的 `cases: [<case id>, ...]` 明确列出它。judge 条目仅仅存在不算覆盖，`cases` 不得用于 check 条目。
reject 的 case 最终 verdict 也必须为 reject：只有未被失败检查覆盖、仅由具名 judge 覆盖时，
才将这些具名 judge 暂按不通过计算，并要求 verdict 为 reject；lint 会注明结论依赖待评审条目。
不通过就修到通过为止。连续 3 次因同一原因失败就停下，把原因写进 `evidence.md` 末尾。

## 结束时

最后一条消息只写：verifier 各层各有几条、几条是 check、建了几个 case、lint 结果、最不确定的两条标准。
