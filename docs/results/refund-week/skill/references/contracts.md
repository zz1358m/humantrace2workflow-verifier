# 输入、交接和可验证边界

## 业务运行

在运行根执行后端，例如 `python input/env.py lookup ORDER`。现有后端把产物写入工作目录的 `output/`；因此不要从 skill 目录调用它。先读当次 env.py/帮助确定入口，不假定未来实现一样。

本文件补充 SKILL 的执行规则，不能成为运行包缺少 references 时的单点依赖。默认三个 stage 在当前任务连续完成，work 文件只是检查点。现有协议 help/status 提前返回、不调用 save；只做预检不会生成原件，须继续执行已授权的逐单流程。只有真实缺失且影响本单决定的事实/规则才阻止相应危险动作。

可用命令是 lookup/refund/restock/escalate/notify/status。status 是批次只读，不追加逐单动作；lookup 会写日志。通知后核数用 status 及已生成文件。不要通过重跑 refund 查支付结果。

当前检查器协议来自可用运行输入中的 env.py，仅将它用作**字段与落盘语义**依据，不作为个人偏好的证据；没有读取 `runs/*/output` 来写正确答案。

- `orders.json`：`day`（ISO 日期）、`daily_refund_cap`、`orders` 映射。订单含 `paid,amount,shipping_fee,shipped,return_received,reason,first_requested_at`；金额为有限分位数，状态字段为布尔值。
- `requests.csv`：`request_id,order,requested_at,reason`。申请条数计原行数；订单按 order 去重，保留所有 request_id。队列时间取后台 first_requested_at，同一时间未规定先后，不强行推断个人偏好。
- `approvals.csv`：`order,decision`，decision 为 approved/rejected；文件缺失表示无新审批，不能伪造审批。
- `prev_state.json` / `state.json`：`day,cap,refunded_today,declined_today,refunds,restocked,escalated,notified`。refunds 是订单到累计退款额映射，notified 是订单到历史模板数组。昨日退款和通知不能因日额度重置而清空。
- `journal.jsonl`：每行 `op,order`；refund 附 `amount,result`（ok/declined），escalate 附 reason，notify 附 template。完整当日日志包括本人与其他执行者已做动作，不能只导出最后会话新增部分。
- `refund_rules.json`（仅有效规则已由输入提供时）：`approval_amount_basis: gross|net` 可解决扣费跨阈值边界；`shipping_applies_unshipped` 可解决未发货买家原因运费边界。不得为了通过检查自造规则。本 skill 不向 input 写这些文件。
- `week_start_state.json`（必要时）：本周周一营业前的后台状态。没有基线时，仅当本次累计已退款订单的最初申请时间均在本周，才可确定累计全量属于本周；否则必须取得后台导出，不能以最初申请日期冒充退款发生日期。
- `history/`：历史日报仅辅助核对。日期写在文件名 `YYYY-MM-DD.md`，或由输入 `history_index.json` 提供文件名到日期的可验证映射。`d1.md` 不自动意味着周一；无日期文件归属留给 O4 核实。work/context.json 中可记录映射依据，但不能凭推测改变检查输入。

后端 pending 的当前定义：曾升级、尚未退款、也未发 rejected 的订单。暂不退/need_return 是另一个分支，不能悄悄把它与后台 pending 混算。若实际后端定义改变，以有效后端契约为准更新适配；本周报说明采用的口径。

## 当日动作与跨日存量

查询队列覆盖全部新旧候选；队列成员不自动获得通知资格。以下按从上到下的优先级，在当前单 lookup 后、任何业务动作前判断；已在当日通知过的单遵循恢复规则，只读既有记录，不重做动作。

候选集合先从今日 requests、有效 approvals、历史未结 escalated/need_return 取得；历史已退款/已驳回不因残留升级记录再次进入待办，但今日再次申请仍查询判重。`orders` 全目录不等于申请表，`first_requested_at` 仅为这些候选排序；目录中的旧日期、当前未见退款记录、输入日期缺口都不能独立证明应补办。O2/O6 保留严格的新旧候选覆盖，O7 另从原输入来源扫描全部实际业务动作，PR3 也检查队列外通知。

| 输入事实 | 当日结果 / 后续存量 | 当日通知 |
| --- | --- | --- |
| 历史实际已退款或已发 rejected 结案 | untouched（不动）；不得再次退款/入库 | 零次 |
| 尚未退款、今日主管驳回 | rejected（驳回）；不退钱 | rejected 一次 |
| 历史升级未结、今日无新申请/审批决定、按有效金额口径仍超审批权限 | untouched（不动）；carry_status=awaiting_approval，不重复升级/退款/入库 | 零次；额度重置本身不解除权限 |
| 未结案、历史已有 need_return、今日无新申请、已发货且仍未签收 | untouched（不动）；carry_status=awaiting_return，继续核签收 | 零次；批准只解除权限关口，不触发重发 |
| 未结案、已发货未签收，但今日有新申请或历史没有 need_return | need_return（当日暂不退）；carry_status=awaiting_return | need_return 一次 |
| 历史升级未结、今日无新申请/审批决定、权限满足且已签收或无需退货，但轮到时整单额度仍不足 | untouched（不动）；carry_status=awaiting_budget，保留原待办，不退款/升级/入库 | 零次；额度重置不是重复升级/通知的理由 |
| 未结案、已签收或无需退货 | 按原因/运费/批准/整单额度判 refunded 或 escalated；过去 need_return 不阻止接续 | 与实际结果相符，一次 |

额度型旧升级在权限内时按轮到时额度重核，足额接续退款，仍不足且无新申请/审批则只查不动，不预占额度，继续下一单；新批准/驳回和新申请走对应分支，仍不足时按当日新分支整单升级。开工额度、日切重置、期末余额都不能替代本单按序余额。上述旧单静默不能泛化为所有旧单都不动。来源和触发条件未知就保留未知，不能用当前 state 中已被本次动作写入的 escalated/notified 倒推开工时已有资格。

不动的旧待签收单不占用额度，不计当日暂不退动作，但不能从结果表或次日核查队列消失。“历史通知”不等于“历史退款”；“今天无动作”不等于“已结案”。未支付、缺失关键字段等仍按 SKILL 的停下规则处理，不能靠此表默认放行。

每日 `outcome` 从真实日志判：成功 refund→refunded，escalate→escalated，need_return 通知→need_return，rejected 通知→rejected，仅 lookup→untouched；若本应有动作却仅查，仍保留未执行差异，不能宣称合法不动。没有执行记录时 outcome=null，不伪造第五类结果；规则不足以判定时 expected_outcome=null 并写具体阻塞。混合/多重动作属于差异，不能只保留最后一个结果。`expected_outcome` 则独立从输入事实推导；正常时一致，异常时两个值都保留。`notification_required` 是预期资格；`notification` 是实际发生记录。日报/周日行的暂不退数字统计当日实际 need_return 的去重订单，不累计历史模板；O2/O5/PR3 同时检查这些实际动作是否本来就应该发生。

## 工作文件

三个阶段的 prompt 各自列出了必要字段。JSON 使用 UTF-8、金额用两位小数字符串、日期使用 ISO；订单标识用后台 ID，不复制买家姓名、联系方式、地址、密钥。交接必须包括来源文件及具体 journal 行，不能只有自然语言“已完成”。work 是执行辅助，不作为 verifier 读取范围；最终待评依据需放 output/DELIVERY.md 及必要的后台原件/回执。

日报的四列是订单、处理、金额、原因。退款行为实付金额，升级行为待审批原额或清楚说明的应退额，其他未退款行写 ¥0.00；首行退款合计只算当日成功退款。已退款重复申请在表里写“不动/重复”，同订单当天多条申请合为一行，但首行申请条数仍含原始多条。

旧待签收仅查询时写“不动（旧单待签收）”，原因说明仍未签收、今日无新申请、未重发、签收后重核；不要写成已退款重复或新的暂不退通知。已误发时如实报告实际通知与错误，不用理想结果替代真实记录。

旧待审批仅查询时写“【待你处理】不动（旧单待审批）”、金额 ¥0.00，待审批额放原因栏，说明等待有效决定且未重发。与今日升级行一起置顶；它属于 pending 存量，不增加当日升级数。预期额度按合法队列及应有退款逐项递减，实际额度按原日志/status 核对；误退后的低余额不是后续错误升级的正当依据。出错日报仍报告实际数字及影响，不删掉越界动作来满足表格覆盖检查。

旧待额度仅查询时也置顶标“【待你处理】不动（旧单待额度）”、金额 ¥0.00；应退额、轮到时余额、仍缺额度、未重发及下一步放原因栏。不增加当日升级数，仍在 pending 中；不能因为今天零通知就隐去待办。`recheck_reason` 可写额度重置，`reopen_trigger` 只有核实按序足额等实际条件后才写恢复，原有新申请/审批决定分别保留。O8 从原输入独立分配额度，拒绝仍缺额度旧单的任何业务动作，不能拿交接计划或执行后的 state 自证资格。

## 历史局部回放

cases 只使用确有文件的 workdir 快照。编译时在 case/input 放 `replay.json`，内容是来源和缺证元数据（不是伪造的历史业务输入），`scope` 为 archived_daily_report 或 archived_weekly_report。不得在新业务输入中创建此标记，且标记不能与 env/orders/prev_state 同时使用。

- 日报片段：input 原样保留 requests.csv 和 journal.jsonl；output 是某版 REPORT.md。可核表内结构、申请数、实际退款/升级、查询、动作顺序；没有订单属性和 state，不能证明 R1 完整交付、R2 全部决策、R5 跨日无重复。
- 周报片段：input 保留当天实际用户请求原文和缺证说明；output 是某版 WEEK.md。可核表格和内部合计，不能认证历史退款事实和 pending。

不适用的脚本会明确返回“未验证完整业务断言”，而不是填造 state、orders 或周初基线。lint 的 accept 只说明可恢复片段未被检查误判；不是历史整批执行通过认证。生产运行没有片段标记时缺输入或后台产物一律 FAIL。

## 来源证明与评审

O1 的状态重放只能证明一致性。普通 JSON 没有签名，存在“真实生成”和“手工伪造但逐字相同”两个不可区分的解释；verifier 不宣称能从文件副本排除后者。O4 评审输入协议、已有输出回执及交付说明所能支持的来源，缺证须写“未证实”；不能强行打勾。

运行 verify.py 所需依赖只有 Python 标准库和 PyYAML（用于读取 verifier 与继承配置）。checks 本身只用标准库、不执行输入中的 env.py、不联网、不写文件；从 --input 推导预期，且不读 cases 或别的输出答案。独立运行每个检查：`python checks/o2_outcomes.py --input DIR --output DIR`，最后一行是布尔 pass 与可定位 detail。

policy 只继承，不新增任务覆盖项。当前 loader 用 kind 与 applies_to 匹配，所以 `[ops,data,comms]` 实际继承 ST1、RP1、RP4、RP5。其余退款标签条目不会自动继承；本任务的可执行业务条目落实这些要求。任务报告脚本将继承的通用习惯用于具体日报/周报字段，不重新复制通用风格条目。
