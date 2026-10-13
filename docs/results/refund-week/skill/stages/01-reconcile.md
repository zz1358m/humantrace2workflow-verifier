# Stage 01：先核旧账和当天输入

本阶段把输入和可执行队列核清，随后由当前执行者继续 Stage 02；没有明确外部阶段分派时，不在此结束任务。运行根下有 `input/`、`work/`、`output/`；读取本 skill 的 SKILL.md、可用的 references/contracts.md 和验收 prompt（未自动提供时读 verifier.yaml）。不要假设能看到其他会话记忆。references 缺失时采用 SKILL 的核心分支和当次后端协议；记录缺失，不虚称已经读过，也不把补充文件缺失扩成整批阻塞。

先读业务日期、requests、prev_state、approvals 和历史汇报。若是续跑，保留 output 内已有后台原件，读其完整当日动作；若昨日文件缺失，不直接当作首日，要用输入范围核实。读取 env.py 的协议和 --help，以文件/API/CLI 为先；只有无可用数据接口时才用界面，不记录点击路径。

从申请和后台最初申请时间合队：把旧的升级未结单、已批待办、需重新核签收的待退货单列全，同一订单多条申请保留所有申请 ID 但只有一个处理实体。只读数据区分待办、已退款、已驳回；缺失的关键字段标 unknown，不用报告补猜。队列先后只来自输入事实。

合队必须先列 `candidate_sources`：今日 requests 行、当次 approvals 行、prev_state 中未结 escalated/need_return 的具体字段。再用 `first_requested_at` 排序；后台目录中只有较早申请时间、没有这些来源的订单不进入业务队列。历史报告可提示取证，但不能仅凭目录、旧日期或“未登记退款”认定待办。核输入状态日期和来源连续性；缺失日无法恢复时保留缺证及影响范围，不从那天的订单日期重建假待办，也不擅改 prev_state。

对旧升级单保留 `prior_escalation_reason` 和新审批决定，并区分 `recheck_reason`（为何要重查）与 `reopen_trigger`（已证明什么条件允许新动作）：额度重置只填前者，不能直接写“已恢复可操作”。只有核查资格而仍待权限审批、无新申请/审批决定时，候选为 lookup_only，待办为 awaiting_approval；权限已满足的额度型旧单标 reassess，交接“轮到时足额才退款，仍不足则 untouched/awaiting_budget、零通知”的条件，不能预先排再次升级。新申请、新批准/驳回按对应分支重判；签收及足额未知留待 02 核实，批准也不免签收。

合队时分别记录“今天是否新申请”“以前是否真退过钱”“以前通知过哪些模板”“当前是否签收”。旧 `need_return` 是待核查存量，不能仅凭入队就给它排一条通知；无今日新申请、仍未签收且没有新驳回的旧单，预期今日只查询，仍保留明日跟进。签收未知则交接待核，不能默认不动或默认通知；已批准也不能绕过签收。按 SKILL 的核心分支及可用的 contracts 决策表标明依据，Stage 02 用实际 lookup 确认。

在此检查点读后端状态及当前额度。可使用批次级 status；需要逐单 lookup 才能补字段时，先看当天是否已通知，避免在已收尾订单后追加查询。只做必要查询，不退款、升级、入库或通知。不能读取 state 就声称满足未来执行时的 lookup 前置；Stage 02 仍须检查查询是否存在且有效。

按实际后端确认落盘时机：help/status 可能只返回数据而不生成 journal/state；文件尚未生成是进入 Stage 02 完成逐单查询与动作的待办，不是手工补文件或停在预检的理由。将原因分类、发货与签收分别记录，明确因未发货取消不能误列为“未签收待退货”或未知买家运费。只有实际触发且会改变当前决定的未知字段才是局部关口；单列它影响哪些后续订单/额度，其他候选继续。

写以下交接（JSON UTF-8；金额使用分位字符串）：

- `work/context.json`：`business_date`、`input_files`（路径及 SHA256）、`backend_command`/工作目录、`backend_persistence`（哪些命令生成原件）、`rules` 及其来源、`history_date_map`（只映射可证日期）、`week_baseline_source`、`resume`、`known_today_actions`、`unknowns`（逐项列影响订单与依赖，不用全局未知阻塞全部）、`next_stage`。
- `work/queue.csv`：`order,request_ids,first_requested_at,source,candidate_sources,approval,prior_escalation_reason,recheck_reason,reopen_trigger,prior_outcome,resume_from,blocked_reason,has_today_request,prior_refund_amount,prior_templates,return_received,carry_status,action_candidate,decision_basis`。request_ids/prior_templates/candidate_sources 用分号分隔，source 区分 new/carryover/both；action_candidate 用 lookup_only/reassess/unknown，不能把候选当已执行。candidate_sources 必须指向输入记录，decision_basis 含权限比较口径、整单应退额及按序足额/不足两种分支；开工额度不充作轮到本单的余额，签收或触发条件未知写 unknown。
- `work/preflight.md`：核对了哪些输入、申请条数与去重单数、有来源旧单覆盖、目录单排除依据、历史连续性、当日已有动作、旧待签收/待审批/待额度的复核条件及零通知依据、可执行性及局部阻塞；不要包含买家身份资料或凭证。

本阶段完成的条件：只读这些文件、原输入和 output 就能知道该处理哪些订单、依据在哪、哪些动作已经做过。未解决的关口显式保留；普通升级分支不阻止继续。保存检查点后立即读取 stages/02-process.md 并执行已授权队列；只有实际被分派为单阶段任务时才交给指定的下一执行者，不能臆定存在“下一会话”。
