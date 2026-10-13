# TASK：改进 skill `{{name}}` 的 workflow，使它在这个人的 verifier 下得分更高

当前目录是本轮独立的临时 sandbox，只包含 skill 与 train 运行结果。
- `skill/SKILL.md`：要改的 workflow。
- `skill/verifier.yaml`、`skill/checks/`：目标函数，**只读**。verifier 已合并个人风格标准。
- `train/`：本轮在 train 样例上的运行结果。每个样例子目录里只有
  `input/`、`output/`（按当前 workflow 做出来的）、`report.json`（verifier 逐条结论）。

读各样例的 `report.json`，找出反复失败的条目，判断是 workflow 的哪一步导致的
（缺了步骤、顺序不对、判断条件含糊、没说清从哪取数、少了检查点），然后修改 `skill/SKILL.md`。

硬性约束：
1. 只改 `skill/SKILL.md`，以及下面要求追加的 `skill/CHANGELOG.md`。verifier、checks、cases 一个字节都不能动；改动数据根目录里的标准或样例会被检测到并整轮作废。
2. 改流程，不改标准：不要在 SKILL.md 里写“忽略某条检查”或教执行者绕过检查。
3. 不要把样例的具体答案写进 SKILL.md；改动必须对没见过的输入同样成立。只读当前 sandbox 的材料，不要到外部查找 held-out 样例或人的保留产出。
4. frontmatter 的 `name` 不变。每次改动控制在解决已观察到的失败，不做无关重写。

把本轮改动与理由追加到 `skill/CHANGELOG.md`（时间、失败条目、改了什么、为什么）。
最后一条消息只写改了哪几处。
