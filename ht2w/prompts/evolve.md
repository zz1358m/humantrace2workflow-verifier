# TASK：根据反馈更新 skill `{{name}}` 的 verifier（产出提案，不直接生效）

当前目录是数据根目录。材料：
- `skills/{{name}}/verifier.yaml`：现行版本。
- `skills/{{name}}/feedback.jsonl`：这个人对历次运行的接受 / 拒绝及备注，每行带 verifier 当时的结论。
- `skills/{{name}}/proposals/*.yaml`：历次影子运行对比得出的差异与建议条目。
- `skills/{{name}}/cases/`：带标签的样例。

要找的是 verifier 与本人判断不一致的地方：verifier 判 accept 而本人拒绝（漏了标准），
或 verifier 判 reject 而本人接受（标准过严或条目本身不对）。据此新增、修改、降权或删除条目。

写两个文件：
- `skills/{{name}}/verifier.proposed.yaml`：完整的新版本，`version` 加一。
- `skills/{{name}}/verifier.proposed.md`：逐条说明改了什么、依据哪几条反馈、预期修正哪些不一致。

硬性约束：
1. 不改现行 `verifier.yaml`，不改 `profile/`。提案要等本人执行 `ht2w approve {{name}}` 才生效。
2. 只凭一次反馈的改动 confidence ≤ 0.5；同一方向出现两次以上才可以设为 hard。
3. objective 层条目只能在有反例说明它本身写错时才改，不能因为难满足而放宽。
4. 新增 check 脚本放 `skills/{{name}}/checks/`，遵守既有约定。
5. 改完运行 `python -m ht2w lint {{name}} --proposed`，必须通过。

最后一条消息只写新增、修改、删除的条目 id。
