# TASK：按 skill 执行一次任务

当前目录是一次运行的沙盒：
- `skill/`：要遵循的 skill（先读 `skill/SKILL.md`）。
- `input/`：本次输入。
- `output/`：把全部产出写到这里（目录已存在）。

严格按 `skill/SKILL.md` 做，包括其中的“交付前验收”：
运行 `python skill/verify.py --input input --output output`，按结果修正。

硬性约束：
0. 如果 `input/` 里有 `env.py`：那是这次任务的环境，所有对外动作都必须通过它执行（`python input/env.py --help`）。
   它会自己把动作记进 `output/journal.jsonl`；不要手写或修改这个日志，动作一旦执行不能撤销。
1. 只写 `output/`。不改 `skill/` 和 `input/`，不读当前目录之外的任何文件。
2. 不要为了通过检查而迎合检查脚本的实现细节；按 skill 的意图把事情做对。
3. 触发 skill 里“必须停下的情况”时，停下，把原因写进 `output/BLOCKED.md`，不要猜着做完。

最后一条消息只写：产出了哪些文件、verify 的结论、TODO 条目的自评。
