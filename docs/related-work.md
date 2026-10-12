# 相关工作调研（2026-10-12）

一句话结论：**“看人操作 → 生成 skill”已经被三家大厂产品化，“被动轨迹 → 任务模型”已有论文，
“skill 与 verifier 共同演化”也有论文；但没有找到任何工作从个人轨迹里学出这个人自己的验收标准。**
提案里的核心主张（要学的是一对 (workflow, verifier)，且 verifier 是个人的）目前是空位。

说明：产品部分的细节多来自二手博客，没有逐一核对官方文档；论文部分只读了摘要或摘要页，数字是作者自报。

## 1. 演示 → skill（已产品化，是直接竞品）

| 工作 | 做法 | 与本项目的差别 |
|---|---|---|
| [Claude Cowork · Record a Skill](https://letsdatascience.com/blog/claude-cowork-record-a-skill-teach-ai-by-demonstration)（Anthropic，2026-07） | 录一次屏并口述决策与例外，生成可复用 Skill | 单次、主动演示、需要口述；没有验收标准，评论称其 “not self-verifying” |
| [Codex · Record & Replay](https://codex.danielvaughan.com/2026/07/06/record-and-replay-programming-by-demonstration-codex-cli-skill-generation-open-agent-skills-standard/)（OpenAI，2026-06） | 录屏与交互 → 推理模型生成 SKILL.md，不存坐标；仅 macOS | SKILL.md 里有一段“验证方法”，但它是模型从一次成功演示里猜的，不来自这个人的纠错行为 |
| [microsoft/skill-recorder](https://github.com/microsoft/skill-recorder)（开源，MIT） | 采集屏幕、窗口、URL、剪贴板、终端命令、语音 → Copilot CLI 重建为“意图 + 步骤” | 采集面与本项目最接近；仍是单次演示，产出面向微软自家 agent |
| [OpenAdapt](https://github.com/OpenAdaptAI/OpenAdapt) | 录制截图与输入事件 → 模型生成回放 | 偏回放，绑定界面 |
| [claude-teach](https://agent-skills.cc/skills/kanoliban-claude-teach)（社区） | 在对话里发现重复三次以上的流程并提议做成 skill | 只看对话，不看屏幕；无 verifier |

共同点：都是**一次、主动、只看主线**。用户要专门演示一遍，系统记录的是“怎么做”。
返工、撤销、回头核对这些行为在一次干净的演示里根本不会出现。

## 2. 被动轨迹 → 任务 / 用户模型（最近的学术工作）

- **[Inducing Task Models from Computer-Use Traces](https://www.alphaxiv.org/abs/2608.20319)**（Jiang, Wang, Chen, Yang；2026-08；[代码](https://github.com/Yucheng-Jiang/task-model-induction)）。
  **与本项目最接近，必须对比。** 输入是被动记录的截图加键鼠事件；三步：VLM 对齐与切分 → 潜在任务归纳（能拆开交错的任务）→
  构建“目标层级 + 带控制流的过程”并互相校正。自报任务聚类 ARI 0.974，步骤还原 74.9%，
  迁移给 coding agent 后留出任务准确率 18.57% 对 14.29%。
  摘要页没有提到学习验收标准或个人偏好——它解决的是提案里的 ② 任务切分和 ③ 的一半（workflow）。
- **[Creating General User Models from Computer Use (GUM)](https://arxiv.org/abs/2505.10831)**（Shaikh 等）。
  从截图构建带置信度的自然语言命题来描述用户，并驱动主动建议。是“用户画像”这条线的代表；
  画像是关于“这个人是谁、在做什么”，不是“这个人怎么验收”，也不产出可执行的检查。
- [Behavior Latticing / Dawn](https://arxiv.org/abs/2604.07629)：从电脑使用观察推断用户动机。
- [Activity Frames](https://arxiv.org/abs/2608.05784)：零模型、确定性地把被动屏幕活动编译成 agent 记忆。本项目的 compile 层思路相同（先确定性压缩，再交给 agent）。
- [PIRA-Bench](https://arxiv.org/abs/2603.08013)：从被动观察流预测用户的下一个意图（提案里留到后面的“预测式抢跑”）。
- [Mining SKILL.md from trajectories](https://www.emergentmind.com/papers/2606.20363)：切分、聚类轨迹得到 skill。
  **值得注意的负面结果**：聚出来的 skill 可读，但对下游策略几乎没帮助（18.5% → 20.5%）。可读不等于有用，所以需要一个目标函数来检验 skill——这正是 verifier 的位置。
- [Screenpipe](https://screenpi.pe/about)（开源）：全天录屏录音加本地检索，是记忆与查询层，不蒸馏 skill。可以作为本项目的一个上游数据源。

## 3. 从 agent 自己的轨迹里归纳 workflow

[Agent Workflow Memory](https://arxiv.org/abs/2409.07429)、SkillWeaver、Agent Skill Induction 等：从 agent 的成功轨迹里提炼可复用子流程。
来源是 agent 轨迹不是人的轨迹，“成功”由基准的评测器给定，没有个人化问题。

## 4. skill 与 verifier 共同演化

- **[EvoSkills / CoEvoSkills](https://arxiv.org/abs/2604.01687)**：Skill Generator 与 Surrogate Verifier 共同演化，在拿不到真实测试时由 verifier 提供反馈。
  去掉 verifier 后 SkillsBench 通过率从 71.1% 掉到 41.1%（据[综述](https://arxiv.org/abs/2607.10113)）。
  这是“verifier 对 skill 质量是决定性的”的现成证据，可以直接引用；但它的 verifier 是任务级、从任务描述合成的，不属于任何人。
- [SkillCoach](https://papers.cool/arxiv/2607.01874)：从真实 rollout 推导过程级 rubric。
- [Agentic Rubrics](https://arxiv.org/abs/2601.04171)：agent 读仓库后写出带权重的 rubric 来给补丁打分。本项目 verifier 条目的形状（一句判据加权重加分层）与它相近。
- [OmegaUse-OfficeVal](https://arxiv.org/abs/2607.27155)：生成的 verifier 经专家打分逐条校准。校准信号来自专家，而不是用户的日常行为。

## 5. 从隐式反馈学个人偏好

- **[PRELUDE / CIPHER](https://www.microsoft.com/en-us/research/publication/aligning-llm-agents-by-learning-latent-preference-from-user-edits/)**（NeurIPS 2024）：
  从用户对 agent 输出的**编辑**里推断潜在偏好，写成自然语言放进 prompt。这是“纠错行为即偏好信号”最直接的先例。
  差别：只有编辑这一种信号、只在写作任务上、偏好用于生成而不是作为可执行的验收。
- [iRULER](https://arxiv.org/abs/2602.12779)（CHI '26）：用户自己定义评价 rubric 并迭代。标准是用户写的，不是从行为里学的。
- 没有找到把撤销、返工、切窗口核对这类**屏幕行为**当作偏好或验收信号的工作（查过，可能有遗漏）。

## 6. 定位

|  | 来源 | 一次 / 持续 | 学 workflow | 学 verifier | verifier 属于个人 |
|---|---|---|---|---|---|
| Record a Skill / Record & Replay / Skill Recorder | 人的主动演示 | 一次 | ✓ | ✗ | – |
| TMI | 人的被动轨迹 | 持续 | ✓ | ✗ | – |
| GUM | 人的被动轨迹 | 持续 | ✗（画像） | ✗ | – |
| AWM / SkillWeaver | agent 轨迹 | 持续 | ✓ | ✗（用基准评测器） | – |
| EvoSkills | 任务描述 | – | ✓ | ✓ | ✗ |
| PRELUDE | 人对输出的编辑 | 持续 | ✗ | 部分（偏好） | ✓ |
| **本项目** | 人的被动轨迹加 agent 对话 | 持续 | ✓ | ✓ | ✓ |

## 7. 对提案的三点影响

1. **workflow 这一半不能再当贡献讲。** 演示 → skill 是产品功能，被动轨迹 → 任务模型有 TMI。
   论文的贡献必须压在 verifier 上：从主线之外的行为学出个人验收标准，并证明它是个人的（提案 §4 的换 verifier 对照实验）。
   ② 任务切分可以直接复用或对比 TMI。
2. **本地 agent 对话日志是被忽略的信号源，而且比屏幕便宜得多。** 上面的工作全在看屏幕。
   但一个重度使用 coding agent 的人，每天在对话里几十次明确表达“这不对”“你核对过吗”“只要 X 不要 Y”——
   这是已经文本化、带时间戳、带上下文（被打回的产出就在上一条）的验收标准，不需要 VLM。
   在这台机器上实测：2026-10-12 一天的日志里有 100 条去重后的用户消息，启发式规则命中 6 次纠正、2 次要求验证、2 次中断、1 次拒绝工具调用
   （规则是高召回的候选筛选，这些数没有人工核对过）。
3. **skill-mining 的负面结果是有利的动机。** “挖出来的 skill 可读但没用”说明缺目标函数；
   EvoSkills 说明有 verifier 时差别很大。两者拼起来正好是提案的论证：verifier 是必要的，而本项目回答它从哪来。
