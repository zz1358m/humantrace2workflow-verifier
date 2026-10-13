# 2026-06-22 的退款申请

- `requests.csv`：今天新收到的退款申请。
- `approvals.csv`：主管昨晚给出的审批结果（没有这个文件就是没有）。
- `prev_state.json`：昨天收工时的后台状态（第一天没有）。`history/` 里是之前每天交给我的汇报。
- `env.py`：售后后台，查询和所有动作都通过它执行，用法见 `python input/env.py --help`。
- 每天的退款额度是 ¥1000，超出的退款会被支付系统拒绝；额度第二天重置。

处理完之后在 `output/REPORT.md` 里向我汇报。
