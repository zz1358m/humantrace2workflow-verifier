# Bench report: refund-week

skill built: `process-daily-refunds`

**filled 3 / 7 days**

| day | R1 | R2 | R3 | R4 | R5 | R6 | R7 | filled |
|---|---|---|---|---|---|---|---|---|
| 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | yes |
| 2 | ✓ | ✗ | ✓ | ✗ | ✓ | ✓ | · | no |
| 3 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | yes |
| 4 | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ | · | no |
| 5 | ✓ | ✗ | ✓ | ✗ | ✓ | ✓ | · | no |
| 6 | ✓ | ✗ | ✓ | ✗ | ✓ | ✓ | · | no |
| 7 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | yes |

## Rubric items that failed

- day 2 `R2` 今天每一单的结果（退多少 / 升级 / 暂不退 / 驳回 / 不动）和我自己处理的一样，包括前几天留下来的单 — W104: 应为 none，实际 wait
- day 2 `R4` 通知买家是这一单当天的最后一个动作，当天恰好通知一次，模板和结果对得上；今天不该动的单不通知 — W104 今天不该通知买家
- day 4 `R1` 产出 journal.jsonl 和 state.json（由后台生成，不是手写的）以及 REPORT.md — 缺少 ['REPORT.md', 'journal.jsonl', 'state.json']
- day 4 `R2` 今天每一单的结果（退多少 / 升级 / 暂不退 / 驳回 / 不动）和我自己处理的一样，包括前几天留下来的单 — W111: 应为 rejected，实际 none；W113: 应为 wait，实际 none；W114: 应为 refund 450.00，实际 none；W115: 应为 refund 480.00，实际 none；W116: 应为 escalate，实际 none；W117: 应为 refund 52.00，实际 none
- day 4 `R4` 通知买家是这一单当天的最后一个动作，当天恰好通知一次，模板和结果对得上；今天不该动的单不通知 — W111 通知了 0 次；W113 通知了 0 次；W114 通知了 0 次；W115 通知了 0 次；W116 通知了 0 次；W117 通知了 0 次
- day 4 `R6` REPORT.md 第一行是一句话结论，里面的退款单数、退款合计、升级单数与后台当天实际一致 — 第一行：''；后台今天：退款 0 单合计 0.00，升级 0 单
- day 5 `R2` 今天每一单的结果（退多少 / 升级 / 暂不退 / 驳回 / 不动）和我自己处理的一样，包括前几天留下来的单 — W111: 应为 none，实际 escalate；W114: 应为 none，实际 refund 450.00；W115: 应为 none，实际 refund 480.00；W116: 应为 none，实际 escalate；W117: 应为 none，实际 refund 52.00；W119: 应为 refund 260.00，实际 escalate；W120: 应为 refund 298.00，实际 escalate；W121: 应为 refund 390.00，实际 escalate
- day 5 `R4` 通知买家是这一单当天的最后一个动作，当天恰好通知一次，模板和结果对得上；今天不该动的单不通知 — W111 今天不该通知买家；W114 今天不该通知买家；W115 今天不该通知买家；W116 今天不该通知买家；W117 今天不该通知买家；W119 模板应为 refunded，实际 escalated；W120 模板应为 refunded，实际 escalated；W121 模板应为 refunded，实际 escalated
- day 6 `R2` 今天每一单的结果（退多少 / 升级 / 暂不退 / 驳回 / 不动）和我自己处理的一样，包括前几天留下来的单 — W119: 应为 none，实际 escalate；W120: 应为 none，实际 escalate；W121: 应为 none，实际 escalate
- day 6 `R4` 通知买家是这一单当天的最后一个动作，当天恰好通知一次，模板和结果对得上；今天不该动的单不通知 — W119 今天不该通知买家；W120 今天不该通知买家；W121 今天不该通知买家

## Hidden style items: 16 / 17 caught

reference days accepted by the built verifier: {'d1': 'reject', 'd2': 'reject', 'd3': 'reject', 'd4': 'reject', 'd7': 'reject'}

- [x] `S1` (day 1) 按申请时间从早到晚处理，不按表格里的行顺序（额度有限，先来的先退） — caught by O2, PR2, PR3
- [x] `S2` (day 1) 买家自己原因的退货，退款要扣掉运费 — caught by O2
- [x] `S3` (day 1) 单笔超过 500 元的不直接退，升级给主管 — caught by O2, P1, PR3, PR4, RP4
- [x] `S4` (day 1) 钱退成功之后才通知买家，通知永远是这一单的最后一步 — caught by PR3, PR4
- [x] `S5` (day 1) 已发货但退货还没签收的不退款，通知买家先寄回 — caught by O2, P1, PR3, PR4, RP4, RP5
- [x] `S10` (day 1) 当日额度不够退整单时，整单升级，不做部分退款 — caught by O2, P1, PR3, PR4, RP4
- [x] `S6` (day 1) 汇报第一行就是一句话结论：几条申请、退了几单合计多少、升级几单、暂不退几单 — caught by RP5
- [x] `S7` (day 1) 每单一行的表格（订单、处理、金额、原因），不写“我先……然后……”的过程叙述 — caught by P1, RP4, RP5, ST1
- [x] `S8` (day 1) 需要她亲自处理的单（升级的）排在表格最前面，并标上【待你处理】 — caught by RP4
- [ ] `S9` (day 1) 金额一律写成 ¥ 加两位小数 — not caught
- [x] `S11` (day 1) 汇报里不贴后台日志和命令，她要看的是结果 — caught by RP5
- [x] `L1` (day 2) 前一天因额度不足没退成的单，第二天和新申请排成一队，按最初申请时间先后处理，所以它们排在最前面 — caught by PR3, ST1
- [x] `L2` (day 2) 主管批准的单，批准后的当天就退，不等买家再来催 — caught by PR3, RP4
- [x] `L3` (day 3) 之前通知过“先寄回”的单，买家寄回签收后再申请要正常退，不算重复 — caught by P1, PR3, ST1
- [x] `L4` (day 3) 之前任何一天已经退过款的订单再来申请，一律不重复退 — caught by O3, O7, P1, PR3, PR4, RP4, ST1
- [x] `L5` (day 4) 主管驳回的单要通知买家（rejected），不退款，也不能放着不管 — caught by O2, P1, PR3
- [x] `L6` (day 7) 周日的周汇总第一行是一句话结论：本周共退几单合计多少、还有几单待处理；下面每天一行 — caught by RP4, RP5, RW1
