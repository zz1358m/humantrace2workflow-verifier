# Stage 02：按队列做完各单，收工核数

本阶段执行已授权的当天退款批次并留下可对账结果，完成后继续 Stage 03。读 SKILL.md、可用的 references/contracts.md、验收 prompt（或 verifier.yaml）、`work/context.json`、`work/queue.csv`、`work/preflight.md`，再读其中引用的原输入及 output 已有后台文件；不依赖前一阶段记忆。补充 contracts 未随运行包携带时，核心分支以 SKILL 为准，接口以当次后端协议核实，不把缺文件本身当退款规则冲突。

先校验输入指纹是否变化，逐项重核队列中的候选和局部关口；preflight 的 unknown 不是永久禁令，也不是已完成结果。数据变化则重新合队，不机械执行旧计划。按队列串行处理：对当前单完成 lookup，读真实返回；把字段与审批、历史和轮到本单时剩余额度一起算出本单分支，核对后再提交该分支的动作。每完成一个动作立即检查后端返回和落盘情况，完成该单收尾再进入下一单。不要预先并发提交一批资金动作。

执行前逐项复核 `candidate_sources`，不能把 Stage 01 的队列本身当授权；仅有订单目录或旧申请时间的候选退回 01 修正，不提交任何业务动作。对历史升级尚待权限审批、今日无新申请/审批决定的单，lookup 后记 untouched/awaiting_approval、notification_required=false，不重复升级或通知。权限满足的旧升级仍核签收和轮到时的完整应退额/余额；签收或无需退货关口通过后，无新申请/审批且余额仍不足时记 untouched/awaiting_budget、notification_required=false，不退款、升级、入库或通知。足额则接续退款；新申请、新审批按对应关口重判，不能把所有旧升级单都跳过。

对合法队列按序维护 `expected_remaining_before/after`（独立应有余额）和 `backend_remaining_before/after`（实际余额）。预期余额只扣应当成功的完整退款；不扣查询、不动、升级，也不把未经资格确认的实际退款计为正当支出。两者不一致时查原日志；若真实误退已挤占额度，冻结受影响后续资金及结果通知并交接，保留后续应退/未完成差异，不顺着错误余额继续升级来制造自洽结果。

对可退款单按 SKILL 的原因适配核定完整应退额，不把所有含“不要了”的理由都当买家原因。明确因未发货取消时无需退货、按全额核定、不入库；额度不足先区分首次/新决定与旧升级存量，前者整单升级、通知，后者无新申请/审批则只查不动，均继续下一单，不因 shipping_fee 非零另造规则疑问。若确有未知规则，记录具体字段、受影响动作和后续依赖；先做完队列中在它之前的明确订单，后续遵守顺序与额度依赖，不能仅留下全批“下一会话再查”。

本单 lookup 后、任何业务动作前，按 SKILL 的核心分支及可用的 contracts 决策表写下 `expected_outcome`、`notification_required`、`notification_template`、`decision_basis`。历史已退款/已结案只查询；旧 `need_return` 无今日新申请且仍未签收、无新驳回时也是 `untouched`，但 `carry_status=awaiting_return`，不是已退款重复或已结案。此分支无退款、升级、入库或通知，不占当日“暂不退”动作数。签收变为真则按正常退款关口重判，即使今天无新申请也不能漏掉；新申请仍未签收走 need_return，新驳回走 rejected。批准本身不触发重发待签收通知。

提交 escalate 前和发通知前都核历史升级、新申请/审批及按序余额，不能仅因实际又升级了就认可 escalated 模板。发通知还须本单 `notification_required=true`；若该分支有退款/升级或适用入库，这些前置动作已有成功回执；模板与该分支相符；完整当日日志中该单通知次数为零。`false` 时直接结束本单；已有一次时按恢复点读取既有结果，不再查询或补发。依据缺失或存在矛盾时停止该单通知，在发送前解决；不能先发再把 verifier 的零通知失败称作待确认规则。不要为这个复核追加通知后的 lookup。

优先用后端命令/API；不自行写后台 state 或 journal。可以用小型调用包装器自动保存必要的 stdout/返回码/导出回执到 `work/`，只保留订单标识和业务字段，不复制密钥或买家个人信息。不要先执行再依据错误返回探索权限或额度。

恢复执行从完整当日日志定位当前单进度，查询今天已经完成的分支时读现有文件或批次 status；状态不明不重复调用。局部业务升级照常完成收尾后继续。真正不可逆错误或缺证时，按 SKILL 的停下规则收束受影响范围，保留原件和实际结果，不为了把计划变成“完成”去补造动作。

完成队列后先取批次 status，再把当日成功退款、升级、暂不退、驳回、不动及历史存量逐项对齐。此处是写报告前的第二个检查点。统计新申请条数、去重订单数和结转数时分别记录口径。周日还需提取本周增量及周末后台 pending，明确待签收是否在该后端 pending 定义内；日期或周初基线缺失就记为无法核实，不用表内加法代替。

保存本次收工 status 的原始回执、实际对账依据与当日日志范围，供 Stage 03 在写报告前核实；不是把开工零值或计划值抄成收工结果。即使存在局部阻塞，也对已经发生的动作核数并进入报告阶段；未执行不得伪装成业务上的“暂不退/不动”。无逐单动作时若后端支持正式导出则由后端导出原件，不支持就保留缺件 FAIL，不手写替代。

此时运行 `python <skill目录>/checks/o2_outcomes.py --input <运行根/input> --output <运行根/output>`、同目录的 `o5_carryover.py`、`o7_eligibility.py`、`o8_budget.py` 和 `pr3_closing.py`，把逐单预期与真实动作的差异写入交接。它们是收工检查，不能代替发送前的关口。错入队、重复升级、误通知或额度连锁差异属于执行问题；保留实际和预期、停止自动补救，不能将实际结果改写成预期，或用“检查器口径问题”消除 FAIL。

交接文件：

- `output/journal.jsonl`、`output/state.json`：后端原始产物，保留原有当日动作。
- `work/results.json`：`business_date`、`request_count`、`orders` 数组；每项含 `order,source,first_requested_at,outcome,expected_outcome,carry_status,refund_amount,proposed_amount,reason,notification,notification_required,notification_template,decision_basis,action_lines,blocked_reason`。outcome 是实际当日结果，expected_outcome 是应有结果，不能合并；已发生/已判定时用 refunded/escalated/need_return/rejected/untouched。没有执行记录时 outcome=null，分支尚不能判断时 expected_outcome=null，并填 blocked_reason；不能伪填 untouched。carry_status 独立保留 awaiting_return 等存量。金额字符串，action_lines 指 journal 行号，notification 留存实际模板与次数。
- `work/reconciliation.json`：`daily` 各当日实际计数/金额，`state_totals`（单列 awaiting_return ID），`week`（适用时的日期映射、基线、逐日值、增量及 pending ID），`comparisons` 数组含 actual/expected/source/match，`unresolved`。旧单仅查询计不动，不因仍待签收就计入当日暂不退；若误发 need_return，实际计数须如实保留并列为差异。
- `work/execution.md`：后端命令入口、原件来源/哈希、是否恢复过、实际异常及不可重做动作；这是交接凭据，不是面向本人的业务报告。

results 每单另保留 `candidate_sources,prior_escalation_reason,recheck_reason,reopen_trigger` 与两套 `remaining_before/after`，decision_basis 记录完整应退额与轮到时余额的比较；重置不能冒充足额恢复。reconciliation 将实际/预期余额差异及造成差异的 journal 行单列。awaiting_approval、awaiting_budget 与 awaiting_return 都是存量，合法只查不动不增加当日升级/暂不退数；保留待额度订单和下次接续条件，今日不动也不等于结案。

完成条件：每个队列订单有实际结果或具体阻塞，每个“成功”均能定位原始记录，数字对账已做。立即读取 stages/03-deliver.md 完成交付；阶段存在阻塞不允许跳过日报和最终 verifier，也不把“没有退款错误”当成“全部已处理”。
