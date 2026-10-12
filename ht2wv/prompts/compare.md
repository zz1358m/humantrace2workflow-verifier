# TASK：对比影子运行与本人的实际产出，找出 verifier 的缺口

当前目录是一次影子运行：
- `input/`：输入。`output/`：skill 自动做出来的。`human/`：这个人自己实际做出来的。
- `report.json`：现有 verifier 对 `output/` 的结论。`skill/`：当时用的 skill（含 `verifier.yaml`）。

本人的版本是事实标准。逐项比较两者的实质差异（内容、数字、结构、措辞、详略、附带的证据），
忽略纯偶然的差异。对每个差异判断：
- verifier 已有条目覆盖且判了不通过 → workflow 的问题，记为 `workflow_gap`。
- verifier 判了通过或根本没有对应条目，但本人版本明显在遵循某个标准 → verifier 的缺口，记为 `verifier_gap`，
  并写出建议新增或修改的条目（格式同 `verifier.yaml` 的 item，`source: corrected`）。
- 看不出规律的个别差异 → `noise`。

只写一个文件 `diff.yaml`：
```yaml
same_enough: true/false        # 本人会不会不改直接用 output/
differences:
  - what: ...
    type: workflow_gap | verifier_gap | noise
    covered_by: 条目 id 或 null
    proposed_item: {...} 或 null
```
一次对比只能说明一次，confidence 不要高于 0.5。最后一条消息只写各类差异的数量。
