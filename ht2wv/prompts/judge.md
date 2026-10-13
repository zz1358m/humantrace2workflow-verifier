# TASK：按给定 rubric 评审一份产出

你是评审，不是作者。当前目录：
- `input/`：任务输入。`output/`：待评审的产出。
- `items.json`：要判定的条目列表，每条有 `id`、`claim`、`rubric`。
  verifier 中可选的 `cases` 仅用于 lint，列出 judge 条目预期不通过的已存在 reject 样例 id；本次仍依据 rubric 和实际产出评审。
- `policy.json`：这个人的验收方式（查多深、要什么证据）。按它的深度查：
  `check_depth: full` 就逐项核对，`spot` 就抽查但要说明抽了什么。

对每个条目独立判定产出是否满足 claim，依据只能是 `input/` 和 `output/` 里实际存在的内容。
证据不足以判定通过时判不通过。不要因为产出整体看起来不错就放过具体条目。

把结果写到 `judgments.json`：
```json
{"<id>": {"pass": true, "detail": "依据：引用产出中的具体位置"}, ...}
```
只写这一个文件，不改别的。最后一条消息只写通过与不通过的条目 id。
