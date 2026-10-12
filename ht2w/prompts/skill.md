# TASK：把任务 `{{name}}` 编译成一个 (workflow, verifier) skill

工作目录是数据根目录。任务定义在 `profile/tasks.yaml` 的 `{{name}}` 条目里；
这个人的画像在 `profile/profile.md`，个人验收层在 `profile/acceptance-style.yaml`；
证据在 `traces/<day>/`（`day.md`、`signals.jsonl`、`events.jsonl`、`shots/`、`blobs/`）。

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
     - id: P1          # preference：这个人在这个任务上特有的标准
       layer: preference
       claim: ...
       how: judge      # 能写成脚本就用 check，写不成才用 judge
       rubric: 评审时具体看什么；给出一个通过的例子和一个不通过的例子
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

## 硬性约束

1. 只写 `skills/{{name}}/`。不改 `traces/`、`profile/`、其他 skill。
2. personal 条目（style / preference）必须引用证据；没有证据的标 `hypothesized`、confidence ≤ 0.3、非 hard。
3. verifier 只能依据产出本身（加上输入）来判定，不能依赖“这个人当时看了什么”这类执行时拿不到的信息。
4. verifier 不能迁就 workflow：不要因为某条标准难以满足就删掉或放宽。
5. `cases/*/output` 里 label 为 accept 的版本不得被用来反推并硬编码进检查脚本（例如把正确答案写死）。
   检查脚本必须从 `--input` 推出期望值。
6. 不要把密钥、口令、他人隐私写进任何产出。

## 自检（必须通过才算完成）

运行 `python -m ht2w lint {{name}}`。它会检查结构，并在每个 case 上跑 verifier，
要求 accept 的 case 不被判 reject、reject 的 case 至少有一条检查脚本不通过或有明确指向它的 judge 条目。
不通过就修到通过为止。连续 3 次因同一原因失败就停下，把原因写进 `evidence.md` 末尾。

## 结束时

最后一条消息只写：verifier 各层各有几条、几条是 check、建了几个 case、lint 结果、最不确定的两条标准。
