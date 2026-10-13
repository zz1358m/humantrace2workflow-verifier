# TASK：多会话 workflow 的第 {{k}} / {{n}} 个会话

当前目录是一次运行的沙盒，所有会话共用它，但会话之间不共享记忆：
- `skill/`：workflow 本身（`skill/SKILL.md` 是总览，本会话的任务书是 `{{stage_file}}`，内容已附在下面）。
- `input/`：本次任务的输入。
- `work/`：会话之间的交接区。先读前面的会话留下的东西，结束前把下一个会话需要的东西写进去。
- `output/`：最终产出。

硬性约束：
1. 只写 `work/` 和 `output/`。不改 `skill/` 和 `input/`，不读当前目录之外的文件。
2. 只做本会话任务书里的事，不要抢后面会话的活，也不要重做前面会话已经交接清楚的活。
3. 不要为了通过检查而迎合检查脚本的实现；按验收标准的意图把事情做对。
4. 触发“必须停下的情况”时，把原因写进 `output/BLOCKED.md` 然后停下。
5. 这是最后一个会话吗：**{{last}}**。如果是：运行 `python skill/verify.py --input input --output output`，
   FAIL 的修掉重跑，TODO 的条目逐条自评，结论写进 `work/final-review.md`。

最后一条消息只写：本会话产出了哪些文件、交接了什么。

---

## 本会话的任务书

{{stage}}

---

{{verifier}}
