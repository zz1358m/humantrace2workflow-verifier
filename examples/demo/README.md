# 示例：合成的一天 → 一个 skill

这个目录是一个完整的数据根目录（`HT2WV_HOME`），内容来自 `ht2wv synth` 生成的合成轨迹，不含任何真人数据。

- `traces/2026-01-05/`：事件、`day.md`、`signals.jsonl`、文件版本 `blobs/`。由代码生成。
- `sessions/*/TASK.md`：`ht2wv distill --backend manual` 生成的两份任务书（画像、建 skill）。由代码生成。
- `profile/`、`skills/weekly-metrics-report/`：**按上面两份任务书手工执行的结果**，不是无头 agent 会话自动跑出来的。
  开发时 Claude Code 不允许嵌套启动、Codex 账户触发了消费上限，两个后端都没能实跑。
- `generic-verifier.yaml`：只保留“文件存在”这一条客观检查的通用 verifier，用来做对照。

可以复现的部分：

```bash
export HT2WV_HOME=examples/demo
ht2wv lint weekly-metrics-report        # 通过：4 个样例，本人留下的 2 个不被判失败，丢弃的 2 个被 O1、P1 判失败
ht2wv eval weekly-metrics-report        # agreement 1.0（只含检查脚本条目，judge 条目未判）
ht2wv eval weekly-metrics-report --verifier examples/demo/generic-verifier.yaml   # agreement 0.5：两个被丢弃的版本都被放过
```

这组数字只说明管线是通的。轨迹是按“会被这些规则检测到”写出来的，不能当作方法有效的证据。
