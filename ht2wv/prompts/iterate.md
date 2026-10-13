# TASK：根据本人的 rubric 反馈改进 skill `{{name}}`

当前目录是数据根目录。上一轮按 `skills/{{name}}/` 执行了一次真实任务，本人按 `request.md` 里的 rubric 逐条勾了结果：
- `{{fb}}/checklist.json`：每条 rubric 过没过，没过的原因。
- `{{fb}}/output/`：那次执行的产出。

做两件事：

1. **修 workflow**：对每条没过的 rubric，判断是哪个 stage 的问题（没取到数、算错、漏了步骤、交接丢了信息、最后没查出来），
   修改 `skills/{{name}}/SKILL.md` 和 `stages/*.md`。
2. **补 verifier**：
   - 没过的 rubric 条目如果 verifier 没拦住（它判了 accept 或没有对应条目），补一条能拦住它的条目，证据写 `request:<id>`，能写成脚本就写成脚本。
   - 再过一遍 `traces/`（`day.md`、`signals.jsonl`）和 `profile/`：有没有这个人明显在坚持、但 verifier 里还没有的标准？
     有轨迹证据的补上；没有证据的不要加。

硬性约束：
1. 只改 `skills/{{name}}/`。不改 `traces/`、`profile/`、`request.md`、`{{fb}}/`。
2. 改动必须对没见过的输入同样成立：不要把这次任务的具体答案写进 workflow 或检查脚本。
3. 不放宽、不删除已有的验收条目，除非它与本人的 rubric 直接矛盾（写明是哪一条）。
4. 改完运行 `python -m ht2wv lint {{name}}`，必须通过。
5. 把改动与理由追加到 `skills/{{name}}/CHANGELOG.md`。

最后一条消息只写：改了哪些 stage、新增或修改了哪些验收条目。
