"""Read-only refund checks. No backend execution, network, golden answers or case IDs.

An archival report has an input replay.json manifest and no runnable backend.
Only its available evidence is checked; runtime inputs may never use that mode.
"""
import argparse
import copy
import csv
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path


class Invalid(ValueError):
    pass


def require(condition, detail):
    if not condition:
        raise Invalid(detail)


def money(value):
    d = Decimal(str(value))
    require(d.is_finite() and d == d.quantize(Decimal('.01')), f'金额 {value!r} 必须是有限的分位金额')
    return d


def cash(value):
    return f'¥{money(value):.2f}'


def read_json(p):
    require(p.is_file(), f'缺少 {p.name}')
    return json.loads(p.read_text(encoding='utf-8'))


def read_csv(p):
    require(p.is_file(), f'缺少 {p.name}')
    with p.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def read_journal(p):
    require(p.is_file(), f'缺少 {p.name}；必须保留后台原始记录')
    result = []
    for n, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            raise Invalid(f'{p.name}:{n} JSON 无法解析：{e}')
        require(isinstance(row, dict) and row.get('op') in {'lookup', 'refund', 'restock', 'escalate', 'notify'},
                f'{p.name}:{n} 缺少或不支持 op；不能静默忽略未知动作')
        require(isinstance(row.get('order'), str) and row['order'], f'{p.name}:{n} 缺少 order')
        result.append(row)
    return result


def first_line(p):
    require(p.is_file(), f'缺少 {p.name}')
    lines = p.read_text(encoding='utf-8').splitlines()
    require(bool(lines) and bool(lines[0].strip()), f'{p.name}:1 必须直接给结论，不能空行')
    return lines[0], lines


def table(lines, headers, name):
    rows = [(i, [s.strip() for s in line.strip().strip('|').split('|')])
            for i, line in enumerate(lines, 1) if line.strip().startswith('|')]
    require(len(rows) >= 2, f'{name} 缺少 Markdown 表格，要求列：{headers}')
    require(rows[0][1] == headers, f'{name}:{rows[0][0]} 表头应为 {headers}，实际 {rows[0][1]}')
    require(len(rows[1][1]) == len(headers) and all(re.fullmatch(r':?-{3,}:?', s) for s in rows[1][1]),
            f'{name}:{rows[1][0]} 表格分隔行不可解析')
    data = rows[2:]
    for n, row in data:
        require(len(row) == len(headers), f'{name}:{n} 应有 {len(headers)} 列，实际 {len(row)}')
    return data


def summary(line, weekly=False):
    patterns = {'refund': r'(?:退款|共退)\s*(\d+)\s*单',
                'amount': r'合计\s*¥\s*(\d+\.\d{2})(?!\d)'}
    if weekly:
        patterns['pending'] = r'(?:仍待处理|待处理|未处理完)\s*(\d+)\s*单'
    else:
        patterns.update(requests=r'(\d+)\s*条申请', escalated=r'升级\s*(\d+)\s*单',
                        need_return=r'暂不退\s*(\d+)\s*单')
    result = {}
    for key, pattern in patterns.items():
        m = re.search(pattern, line)
        require(m is not None, f'首行缺少可读指标 {key}；实际：{line}')
        result[key] = money(m[1]) if key == 'amount' else int(m[1])
    require(not re.match(r'\s*(#|您好|你好|首先|本周我)', line), '首行应为一句结果结论，不能用标题、寒暄或过程开头')
    require(len([s for s in re.split(r'[。！？!?]', line) if s.strip()]) == 1, '首行须为一句结论')
    return result


def clean_report(lines, name):
    for n, line in enumerate(lines, 1):
        require(not re.search(r'您好|你好|首先我|然后我|接着我|python\s+.*env\.py|```|"op"\s*:', line),
                f'{name}:{n} 删除寒暄、逐步执行叙述、命令或日志；保留结果及原因')
        for m in re.finditer(r'¥\s*(\d+(?:\.\d+)?)', line):
            # The retained report uses ¥500 as a policy threshold in a reason.
            is_rule = m[1] == '500' and ('审批' in line or '权限' in line) and n > 1
            require(is_rule or re.fullmatch(r'\d+\.\d{2}', m[1]), f'{name}:{n} 金额 {m[0]} 应带两位小数')
        require(not re.search(r'\d+(?:\.\d+)?\s*元', line), f'{name}:{n} 账款应使用 ¥ 加两位小数')


class Context:
    def __init__(self, inp, out):
        self.inp, self.out = Path(inp), Path(out)
        self.scope = 'operation'
        manifest = self.inp / 'replay.json'
        if manifest.exists():
            m = read_json(manifest)
            require(not any((self.inp / f).exists() for f in ('env.py', 'orders.json', 'prev_state.json')),
                    '历史片段 replay.json 不可与真实业务输入并用；删除回放标记并执行全量验收')
            require(m.get('scope') in {'archived_daily_report', 'archived_weekly_report'} and m.get('origin')
                    and m.get('unavailable'), 'replay.json 必须明确历史片段范围、来源和缺失证据')
            self.scope = m['scope']
        self.live = self.scope == 'operation'
        self.base = read_json(self.inp / 'orders.json') if self.live else {}
        if self.live:
            require(isinstance(self.base, dict), 'orders.json 须为对象')
            require(all(k in self.base for k in ('day', 'daily_refund_cap', 'orders')),
                    'orders.json 必须含 day、daily_refund_cap、orders')
            require(isinstance(self.base['orders'], dict), 'orders.json.orders 须为订单 ID 到字段对象的映射')
            require(money(self.base['daily_refund_cap']) >= 0, 'orders.json.daily_refund_cap 不可为负数')
        self.orders = self.base.get('orders', {})
        self.prev = read_json(self.inp / 'prev_state.json') if self.live and (self.inp / 'prev_state.json').exists() else {}
        self.requests = read_csv(self.inp / 'requests.csv') if self.scope != 'archived_weekly_report' else []
        self.approvals = {}
        if self.live and (self.inp / 'approvals.csv').exists():
            for r in read_csv(self.inp / 'approvals.csv'):
                oid, decision = r.get('order'), r.get('decision')
                require(oid in self.orders and decision in {'approved', 'rejected'}, f'approvals.csv 无效审批：{r}')
                require(oid not in self.approvals or self.approvals[oid] == decision, f'{oid} 审批冲突，不能猜')
                self.approvals[oid] = decision
        self.journal = read_journal(self.out / 'journal.jsonl') if self.live else (
            read_journal(self.inp / 'journal.jsonl') if self.scope == 'archived_daily_report' else [])
        self.by_order = defaultdict(list)
        for n, r in enumerate(self.journal, 1):
            self.by_order[r['order']].append((n, r))

    def absent(self, purpose):
        return f'不适用完整业务断言：{self.scope} 仅历史报告片段；缺失证据不算 {purpose} 已验证'

    def day(self):
        return dt.date.fromisoformat(self.base['day'])

    def refund_terms(self, oid):
        """Amount and authority from input facts, never from actual cap usage."""
        o = self.orders[oid]
        amount, fee = money(o['amount']), money(o['shipping_fee'])
        require(amount > 0 and 0 <= fee <= amount, f'{oid} 金额/运费非法')
        rules = read_json(self.inp / 'refund_rules.json') if (self.inp / 'refund_rules.json').exists() else {}
        buyer = bool(re.search(r'不想要|买家原因', o['reason']))
        known_full = bool(re.search(r'质量|发错|未发货|没发货', o['reason']))
        require(buyer or known_full, f'{oid} 未识别的退款原因 {o["reason"]!r}；需要有效分类规则')
        if buyer and not o['shipped'] and fee:
            require('shipping_applies_unshipped' in rules, f'{oid} 未发货买家原因是否扣运费缺少明确规则')
        deduct = buyer and (o['shipped'] or rules.get('shipping_applies_unshipped', False))
        due = amount - fee if deduct else amount
        require(due > 0, f'{oid} 应退额 {due} 无有效自动处置规则')
        basis = rules.get('approval_amount_basis')
        require(basis in (None, 'gross', 'net'), 'approval_amount_basis 只能为 gross/net')
        if due <= 500 < amount and self.approvals.get(oid) != 'approved':
            require(basis is not None, f'{oid} 原额 {cash(amount)} / 扣费后 {cash(due)} 跨 ¥500.00；须明确审批比较字段')
        return due, due if basis == 'net' else amount

    def unchanged_escalation(self, oid):
        """A prior unresolved escalation without a fresh request or decision."""
        return (oid in self.prev.get('escalated', {}) and oid not in self.approvals
                and not any(r['order'] == oid for r in self.requests)
                and money(self.prev.get('refunds', {}).get(oid, 0)) <= 0
                and 'rejected' not in self.prev.get('notified', {}).get(oid, []))

    def awaiting_approval(self, oid):
        """An existing approval wait is not a fresh daily escalation.

        A cap-only carryover can resume when cap resets; a fresh application or
        approval decision must still follow its own current-day branch.
        """
        if not self.unchanged_escalation(oid):
            return False
        _, authority_amount = self.refund_terms(oid)
        return authority_amount > 500

    def queue(self):
        ids = set()
        for row in self.requests:
            require(row.get('order') and row.get('requested_at'), f'requests.csv 行缺字段：{row}')
            ids.add(row['order'])
        refunded = self.prev.get('refunds', {})
        notified = self.prev.get('notified', {})
        for oid in set(self.prev.get('escalated', {})) | set(notified) | set(self.approvals):
            if money(refunded.get(oid, 0)) > 0 or 'rejected' in notified.get(oid, []):
                continue
            if oid in self.prev.get('escalated', {}) or oid in self.approvals or 'need_return' in notified.get(oid, []):
                ids.add(oid)
        for oid in ids:
            require(oid in self.orders, f'{oid} 没有后台订单，不能从报告猜订单状态')
            require(self.orders[oid].get('first_requested_at'), f'{oid} 缺少最初申请时间')
        return sorted(ids, key=lambda oid: (dt.datetime.fromisoformat(self.orders[oid]['first_requested_at']), oid))

    def expected(self):
        remaining = money(self.base['daily_refund_cap'])
        current = {r['order'] for r in self.requests}
        expected = {}
        # Equal timestamps have no personal tie-break evidence. Resolve only that
        # free ordering choice by actual first mutation; amounts still come from input.
        first_action = {o: next((n for n, r in rows if r['op'] != 'lookup'), float('inf'))
                        for o, rows in self.by_order.items()}
        queue = sorted(self.queue(), key=lambda o: (dt.datetime.fromisoformat(self.orders[o]['first_requested_at']),
                                                    first_action.get(o, float('inf')), o))
        for oid in queue:
            o = self.orders[oid]
            require(all(k in o for k in ('paid', 'amount', 'shipping_fee', 'shipped', 'return_received', 'reason')),
                    f'{oid} 后台缺少支付、金额、运费、发货、签收或原因字段')
            for k in ('paid', 'shipped', 'return_received'):
                require(isinstance(o[k], bool), f'{oid}.{k} 必须是布尔值')
            amount, fee = money(o['amount']), money(o['shipping_fee'])
            require(amount > 0 and 0 <= fee <= amount, f'{oid} 金额/运费非法')
            prior = self.prev.get('notified', {}).get(oid, [])
            result = {'amount': Decimal('0'), 'template': None, 'restock': False}
            if money(self.prev.get('refunds', {}).get(oid, 0)) > 0 or 'rejected' in prior:
                result['outcome'] = 'untouched'
            elif self.approvals.get(oid) == 'rejected':
                result.update(outcome='rejected', template='rejected')
            elif not o['paid']:
                raise Invalid(f'{oid} 未支付订单无轨迹规则；先取得有效业务规则，禁止猜测退款/驳回')
            elif self.awaiting_approval(oid):
                result.update(outcome='untouched', carry_status='awaiting_approval', reason='approval_unchanged')
            elif o['shipped'] and not o['return_received']:
                template = 'need_return' if oid in current or 'need_return' not in prior else None
                # Outstanding return status is not a new daily business action.
                # Keep it in the lookup queue without repeating yesterday's notice.
                result.update(outcome='need_return' if template else 'untouched', template=template,
                              carry_status='awaiting_return', reason='return_not_received')
            else:
                due, threshold_value = self.refund_terms(oid)
                if threshold_value > 500 and self.approvals.get(oid) != 'approved':
                    result.update(outcome='escalated', template='escalated', due=due, reason='approval')
                elif due > remaining:
                    if self.unchanged_escalation(oid):
                        result.update(outcome='untouched', carry_status='awaiting_budget', due=due,
                                      remaining=remaining, reason='cap_still_insufficient')
                    else:
                        result.update(outcome='escalated', template='escalated', due=due, reason='cap')
                else:
                    result.update(outcome='refunded', amount=due, template='refunded', restock=o['shipped'] and o['return_received'])
                    remaining -= due
            expected[oid] = result
        return expected


def artifacts(c):
    if not c.live:
        return c.absent('后台生成与累计状态')
    require((c.out / 'REPORT.md').is_file(), '缺少 REPORT.md')
    if c.day().weekday() == 6:
        require((c.out / 'WEEK.md').is_file(), '周日缺少 WEEK.md')
    state = read_json(c.out / 'state.json')
    if c.prev:
        require(dt.date.fromisoformat(c.prev['day']) == c.day() - dt.timedelta(days=1),
                f'prev_state.json.day 应为昨日 {c.day()-dt.timedelta(days=1)}，实际 {c.prev["day"]}')
        replay = copy.deepcopy(c.prev)
        replay.update(day=c.base['day'], cap=c.base['daily_refund_cap'], refunded_today=0, declined_today=[])
    else:
        replay = dict(day=c.base['day'], cap=c.base['daily_refund_cap'], refunded_today=0,
                      declined_today=[], refunds={}, restocked=[], escalated={}, notified={})
    for n, row in enumerate(c.journal, 1):
        oid, op = row['order'], row['op']
        require(oid in c.orders, f'journal.jsonl:{n} {oid} 不在输入后台订单中')
        if op == 'refund':
            amount = money(row['amount'])
            expected_result = 'declined' if money(replay['refunded_today']) + amount > money(replay['cap']) else 'ok'
            require(row.get('result') == expected_result, f'journal.jsonl:{n} {oid} 支付结果应为 {expected_result}')
            if expected_result == 'ok':
                replay['refunded_today'] = float(money(replay['refunded_today']) + amount)
                replay['refunds'][oid] = float(money(replay['refunds'].get(oid, 0)) + amount)
            else:
                replay['declined_today'].append(oid)
        elif op == 'restock':
            replay['restocked'].append(oid)
        elif op == 'escalate':
            require(bool(row.get('reason')), f'journal.jsonl:{n} {oid} 升级缺少原因')
            replay['escalated'][oid] = row['reason']
        elif op == 'notify':
            require(row.get('template') in {'refunded', 'escalated', 'need_return', 'rejected'}, f'journal.jsonl:{n} 通知模板无效')
            replay['notified'].setdefault(oid, []).append(row['template'])
    for key, value in replay.items():
        require(key in state and state[key] == value,
                f'state.json.{key} 与昨日状态+当日日志不一致；期望 {value!r}，实际 {state.get(key)!r}；不要手改后台文件')
    return '必需文件可解析；昨日历史与当日日志能重建最终 state（文件副本不能独立证明调用来源）'


def outcomes(c):
    if not c.live:
        return c.absent('逐单业务结果')
    expected = c.expected()
    require(set(c.by_order) == set(expected),
            f'应查询完整新旧队列；缺少 {sorted(set(expected)-set(c.by_order))}；额外订单 {sorted(set(c.by_order)-set(expected))}')
    for oid, e in expected.items():
        rows = [r for _, r in c.by_order[oid]]
        refunds = [r for r in rows if r['op'] == 'refund']
        escalations = [r for r in rows if r['op'] == 'escalate']
        require(len(refunds) == int(e['outcome'] == 'refunded'), f'{oid} 期望 {e["outcome"]}，退款调用次数实际 {len(refunds)}')
        if refunds:
            require(refunds[0].get('result') == 'ok' and money(refunds[0]['amount']) == e['amount'],
                    f'{oid} 应一次成功退款 {cash(e["amount"])}，实际 {refunds}')
        require(len(escalations) == int(e['outcome'] == 'escalated'), f'{oid} 期望 {e["outcome"]}，升级调用次数实际 {len(escalations)}')
        if e['outcome'] == 'untouched':
            require(all(r['op'] == 'lookup' for r in rows),
                    f'{oid} 今日应不动（已退款/已结案、旧待签收、仍待审批或额度仍不足），只能查询，不可修改或通知')
        if e['outcome'] in {'need_return', 'rejected'}:
            notices = [r.get('template') for r in rows if r['op'] == 'notify']
            require(notices == [e['template']],
                    f'{oid} 期望 {e["outcome"]}，应有一次 {e["template"]} 通知，实际 {notices}')
            require(not any(r['op'] == 'restock' for r in rows), f'{oid} 未退款不得入库')
    return f'{len(expected)} 个订单按输入独立推导的结果全部对应，含遗留及批准/驳回单'


def carryover_inactivity(c):
    """Independent R2/R4 guard: do not reuse expected()'s branch decision."""
    if not c.live:
        return c.absent('未变化旧待签收单的不动与零通知')
    current = {r['order'] for r in c.requests}
    checked = 0
    for oid, prior in c.prev.get('notified', {}).items():
        if ('need_return' not in prior or oid in current or 'rejected' in prior
                or money(c.prev.get('refunds', {}).get(oid, 0)) > 0
                or c.approvals.get(oid) == 'rejected'):
            continue
        require(oid in c.orders, f'{oid} 旧待签收单缺少当前后台字段，不能猜测不动')
        o = c.orders[oid]
        require(isinstance(o.get('shipped'), bool) and isinstance(o.get('return_received'), bool),
                f'{oid} 缺少有效发货/签收字段，不能判定是否仍待签收')
        if not o['shipped'] or o['return_received']:
            continue
        indexed = c.by_order.get(oid, [])
        require(any(r['op'] == 'lookup' for _, r in indexed), f'{oid} 旧待签收单仍须当天查询，不能漏单')
        mutations = [(n, r['op']) for n, r in indexed if r['op'] != 'lookup']
        require(not mutations,
                f'{oid} 旧 need_return 无新申请且仍未签收，今日应不动、零通知；实际动作（日志行,op）：{mutations}')
        checked += 1
    return f'{checked} 个未变化旧待签收单均保留查询、无业务动作及通知；不将待签收存量当作今日暂不退动作'


def eligibility(c):
    """R2/R4 scope guard independent of queue() and expected().

    Inspect every logged mutation, including orders the decision engine omits.
    Collect all violations so an extra order cannot mask another wrong action.
    """
    if not c.live:
        return c.absent('当日动作资格与旧审批单静默')
    current = {r['order'] for r in c.requests}
    prior_notices = c.prev.get('notified', {})
    candidates = current | set(c.approvals) | set(c.prev.get('escalated', {}))
    candidates |= {o for o, templates in prior_notices.items() if 'need_return' in templates}
    errors = []
    for oid, indexed in c.by_order.items():
        mutations = [(n, r['op']) for n, r in indexed if r['op'] != 'lookup']
        if not mutations:
            continue
        if oid not in candidates:
            errors.append(f'{oid} 无今日申请、审批或历史未结待办来源，禁止业务动作/通知：{mutations}')
        elif (money(c.prev.get('refunds', {}).get(oid, 0)) > 0
              or 'rejected' in prior_notices.get(oid, [])):
            errors.append(f'{oid} 历史已退款/结案，禁止业务动作/通知：{mutations}')
        elif c.awaiting_approval(oid):
            errors.append(f'{oid} 旧升级仍待审批，无新申请/审批决定，今日应不动、零通知：{mutations}')
    require(not errors, '；'.join(errors))
    return '所有已发生业务动作均有输入来源；目录/最初申请时间不授权，仍待审批旧单零业务动作、零通知'


def budget_waits(c):
    """Independently allocate input-based cap; never trust expected()/queue().

    Share only money/rule parsing with the outcome engine. Neither actual
    refunds, final state nor a work handoff may redefine the available cap.
    This also lets O6 recognize a legitimate lookup-only budget carryover.
    """
    current = {r['order'] for r in c.requests}
    notices = c.prev.get('notified', {})
    refunds = c.prev.get('refunds', {})
    escalated = set(c.prev.get('escalated', {}))
    closed = {o for o, a in refunds.items() if money(a) > 0}
    closed |= {o for o, ts in notices.items() if 'rejected' in ts}
    targets = escalated - current - set(c.approvals) - closed
    if not targets:
        return {}
    candidates = current | ((escalated | set(c.approvals)
                             | {o for o, ts in notices.items() if 'need_return' in ts}) - closed)
    for oid in candidates:
        require(oid in c.orders and c.orders[oid].get('first_requested_at'),
                f'{oid} 缺少后台订单/最初申请时间，不能独立核额度存量')
    first_action = {o: next((n for n, r in rows if r['op'] != 'lookup'), float('inf'))
                    for o, rows in c.by_order.items()}
    ordered = sorted(candidates, key=lambda o: (dt.datetime.fromisoformat(c.orders[o]['first_requested_at']),
                                                first_action.get(o, float('inf')), o))
    remaining, waits = money(c.base['daily_refund_cap']), {}
    for oid in ordered:
        if oid not in closed and c.approvals.get(oid) != 'rejected':
            o = c.orders[oid]
            for field in ('paid', 'shipped', 'return_received'):
                require(isinstance(o.get(field), bool), f'{oid}.{field} 缺少有效布尔值，不能独立核额度存量')
            require(o['paid'], f'{oid} 未支付订单无有效处置规则，不能推定后续可用额度')
            if not o['shipped'] or o['return_received']:
                due, authority = c.refund_terms(oid)
                if authority <= 500 or c.approvals.get(oid) == 'approved':
                    if due <= remaining:
                        # Reserve the rightful refund even if execution omitted it.
                        remaining -= due
                    elif oid in targets:
                        waits[oid] = {'due': due, 'remaining': remaining}
        targets.discard(oid)
        if not targets:
            break  # Later unrelated unknowns cannot hide this guard's findings.
    return waits


def budget_inactivity(c):
    """R2/R4: catch every repeated action on an unchanged budget wait."""
    if not c.live:
        return c.absent('旧升级轮到时仍缺额度的不动与零通知')
    waits, errors = budget_waits(c), []
    for oid, facts in waits.items():
        indexed = c.by_order.get(oid, [])
        if not any(r['op'] == 'lookup' for _, r in indexed):
            errors.append(f'{oid} 旧待额度单仍须当天查询，不能漏单')
        mutations = [(n, r['op']) for n, r in indexed if r['op'] != 'lookup']
        if mutations:
            errors.append(f'{oid} 旧升级无新申请/审批，轮到时应有余额 {cash(facts["remaining"])}'
                          f' 不足整单 {cash(facts["due"])}，今日应不动、零通知；'
                          f'实际动作（日志行,op）：{mutations}')
    require(not errors, '；'.join(errors))
    return f'{len(waits)} 个旧待额度单按原输入独立分配后仍不足，均有查询、零业务动作、零通知；待办继续保留'


def payments(c):
    if not c.live:
        return c.absent('支付拒绝与跨日重复')
    seen = {o for o, a in c.prev.get('refunds', {}).items() if money(a) > 0}
    for n, r in enumerate(c.journal, 1):
        if r['op'] != 'refund':
            continue
        oid = r['order']
        require(r.get('result') == 'ok', f'journal.jsonl:{n} {oid} 出现退款失败/支付拒绝；后续成功不能抵消')
        require(oid not in seen, f'journal.jsonl:{n} {oid} 已退过款，不能拆退或跨日再退')
        require(money(r['amount']) > 0, f'journal.jsonl:{n} {oid} 退款必须为正金额')
        seen.add(oid)
    state = read_json(c.out / 'state.json')
    require(not state.get('declined_today'), f'state.json.declined_today 非空：{state.get("declined_today")}')
    return '无支付拒绝、非正金额、拆分退款或跨日重复退款'


def lookup(c):
    if c.scope == 'archived_weekly_report':
        return c.absent('查询前置')
    seen = set()
    for n, r in enumerate(c.journal, 1):
        if r['op'] == 'lookup':
            seen.add(r['order'])
        else:
            require(r['order'] in seen, f'journal.jsonl:{n} {r["order"]} 的 {r["op"]} 之前缺少当天 lookup')
    return '每个非查询动作前均有当天该订单 lookup；未借用昨日查询'


def queue_order(c):
    if c.scope == 'archived_weekly_report':
        return c.absent('新旧队列顺序')
    if c.live:
        times = {o: dt.datetime.fromisoformat(c.orders[o]['first_requested_at']) for o in c.queue()}
    else:
        times = {}
        for r in c.requests:
            t = dt.datetime.fromisoformat(r['requested_at'])
            times[r['order']] = min(times.get(r['order'], t), t)
    order = []
    closed = set()
    current = None
    for n, r in enumerate(c.journal, 1):
        if r['op'] == 'lookup':
            continue
        oid = r['order']
        require(oid in times, f'journal.jsonl:{n} {oid} 无最初申请时间，不能验证队列')
        if oid != current:
            require(oid not in closed, f'journal.jsonl:{n} {oid} 动作与其他订单交错；应逐单完成再继续')
            if current is not None:
                closed.add(current)
            order.append(oid)
            current = oid
    for a, b in zip(order, order[1:]):
        require(times[a] <= times[b], f'实际 {a}({times[a]}) 在 {b}({times[b]}) 前处理；应按最初申请时间')
    return '实际业务动作按最初申请时间串行推进；同时间不强制订单号顺序'


def closing(c):
    if not c.live:
        if c.scope == 'archived_weekly_report':
            return c.absent('逐单收尾')
        expected = {}
        for oid, indexed in c.by_order.items():
            rows = [r for _, r in indexed]
            template = 'refunded' if any(r['op'] == 'refund' for r in rows) else ('escalated' if any(r['op'] == 'escalate' for r in rows) else None)
            expected[oid] = {'template': template, 'restock': None}
    else:
        expected = c.expected()
        for oid in c.by_order.keys() - expected.keys():
            # R4 applies to every notice, not only members of our expected queue.
            expected[oid] = {'template': None, 'restock': False}
    for oid, e in expected.items():
        indexed = c.by_order.get(oid, [])
        rows = [r for _, r in indexed]
        ns = [i for i, r in enumerate(rows) if r['op'] == 'notify']
        require(len(ns) == int(e['template'] is not None), f'{oid} 当天通知应为 {int(e["template"] is not None)} 次，实际 {len(ns)}')
        if ns:
            require(ns[0] == len(rows)-1, f'{oid} 通知不是该单当天最后动作；通知后也不可 lookup')
            require(rows[ns[0]].get('template') == e['template'], f'{oid} 通知模板应为 {e["template"]}，实际 {rows[ns[0]].get("template")}')
        rs = [i for i, r in enumerate(rows) if r['op'] == 'restock']
        if e['restock'] is not None:
            require(len(rs) == int(e['restock']), f'{oid} 适用入库次数应为 {int(e["restock"])}，实际 {len(rs)}')
        for i in rs:
            require(any(r['op'] == 'refund' and r.get('result') == 'ok' for r in rows[:i]), f'{oid} 入库前必须退款成功')
            require(not ns or i < ns[0], f'{oid} 入库须在通知之前')
    return '当天应通知单恰好一次且模板相符、通知最后，适用入库在退款成功后'


def daily_facts(c):
    """Actual daily totals, independent of unresolved business-rule decisions."""
    refunds = [r for r in c.journal if r['op'] == 'refund' and r.get('result') == 'ok']
    escalated = {r['order'] for r in c.journal if r['op'] == 'escalate'}
    waiting = {r['order'] for r in c.journal if r['op'] == 'notify' and r.get('template') == 'need_return'}
    return dict(requests=len(c.requests), refund=len(refunds), amount=sum((money(r['amount']) for r in refunds), Decimal(0)),
                escalated=len(escalated), need_return=len(waiting))


def daily_headline(c):
    line, _ = first_line(c.out / 'REPORT.md')
    s = summary(line)
    for key, value in daily_facts(c).items():
        require(s[key] == value, f'REPORT.md:1 {key} 应为 {value}，实际 {s[key]}；以输入申请和后台当日记录重写')


def completion(c):
    """Lifecycle coverage without expected(): a plan or BLOCKED is not delivery.

    This checks execution and closing coverage, not the correct choice or amount
    of a refund/escalation. O2, O3 and PR3 retain those separate obligations.
    """
    if not c.live:
        return c.absent('整批执行与交付完成')
    daily_headline(c)
    current = {r['order'] for r in c.requests}
    targets = set(c.queue())
    require(set(c.by_order) == targets,
            f'批次未完整执行；缺少订单 {sorted(targets-set(c.by_order))}；额外订单 {sorted(set(c.by_order)-targets)}')
    budget_idle = budget_waits(c)
    for oid in c.queue():
        rows = [r for _, r in c.by_order[oid]]
        require(rows and rows[0]['op'] == 'lookup', f'{oid} 未完成当天查询，预检/status 不能代替逐单执行')
        prior = c.prev.get('notified', {}).get(oid, [])
        o = c.orders[oid]
        closed = money(c.prev.get('refunds', {}).get(oid, 0)) > 0 or 'rejected' in prior
        idle = (oid not in current and 'need_return' in prior and c.approvals.get(oid) != 'rejected'
                and o.get('shipped') is True and o.get('return_received') is False)
        if closed or idle or c.awaiting_approval(oid) or oid in budget_idle:
            require(all(r['op'] == 'lookup' for r in rows), f'{oid} 今日不动单只能查询、零通知')
            continue
        notices = [r for r in rows if r['op'] == 'notify']
        require(len(notices) == 1 and rows[-1]['op'] == 'notify',
                f'{oid} 尚未收尾：应通知单须恰好一次且最后通知，实际 {len(notices)} 次；仅查询/候选/阻塞说明不算完成')
        template = notices[0]['template']
        refunds = [r for r in rows if r['op'] == 'refund']
        escalations = [r for r in rows if r['op'] == 'escalate']
        if template == 'refunded':
            require(len(refunds) == 1 and refunds[0].get('result') == 'ok' and not escalations,
                    f'{oid} refunded 通知缺少唯一成功退款分支')
        elif template == 'escalated':
            require(len(escalations) == 1 and not refunds, f'{oid} escalated 通知缺少唯一整单升级分支')
        else:
            require(template in {'need_return', 'rejected'} and not refunds and not escalations
                    and not any(r['op'] == 'restock' for r in rows), f'{oid} 非退款通知与实际业务动作冲突')
    return f'{len(targets)} 个新旧候选均实际查询并完成应有收尾，日报首行与实际当日记录一致；分支与金额正确性另由 O2/O3/PR3 核验'


def daily(c):
    if c.scope == 'archived_weekly_report':
        return c.absent('日报')
    daily_headline(c)  # A rule gap must not hide an incorrect actual daily total.
    _, lines = first_line(c.out / 'REPORT.md')
    clean_report(lines, 'REPORT.md')
    rows = table(lines, ['订单', '处理', '金额', '原因'], 'REPORT.md')
    refunds = [r for r in c.journal if r['op'] == 'refund' and r.get('result') == 'ok']
    escalated = {r['order'] for r in c.journal if r['op'] == 'escalate'}
    expected = c.expected() if c.live else None
    ids = [r[0] for _, r in rows]
    require(len(set(ids)) == len(ids), 'REPORT.md 表格须一单一行，同订单多条申请不可重复列结果')
    targets = set(expected) if expected is not None else {r['order'] for r in c.requests}
    require(set(ids) == targets, f'REPORT.md 逐单表缺少 {sorted(targets-set(ids))}，多列 {sorted(set(ids)-targets)}')
    refund_amounts = {r['order']: money(r['amount']) for r in refunds}
    pending_waits = {o for o, e in (expected or {}).items()
                     if e.get('carry_status') in {'awaiting_approval', 'awaiting_budget'}}
    no_more_escalations = False
    for n, row in rows:
        oid, action, amount, reason = row
        require(re.fullmatch(r'¥\d+\.\d{2}', amount) is not None, f'REPORT.md:{n} 金额栏 {amount!r} 应为 ¥0.00 格式')
        require(bool(reason), f'REPORT.md:{n} {oid} 缺少原因')
        if oid in escalated or oid in pending_waits:
            require(not no_more_escalations and '【待你处理】' in action,
                    f'REPORT.md:{n} {oid} 升级单须在普通行前标【待你处理】')
            if oid in pending_waits and oid not in escalated:
                require('不动' in action and money(amount[1:]) == 0,
                        f'REPORT.md:{n} {oid} 旧待审批/待额度今日应标不动、金额 ¥0.00；存量不冒充今日升级')
            else:
                require('升级' in action, f'REPORT.md:{n} {oid} 实际升级须写升级')
            if c.live and oid in escalated:
                require(money(amount[1:]) == money(c.orders[oid]['amount']) or money(amount[1:]) == expected[oid].get('due'),
                        f'REPORT.md:{n} {oid} 待审批金额必须来自该订单金额/应退额，不混入退款合计')
        else:
            no_more_escalations = True
            require('【待你处理】' not in action, f'REPORT.md:{n} {oid} 非升级/待办行不应冒充待本人处理')
            if oid in refund_amounts:
                require('已退款' in action and money(amount[1:]) == refund_amounts[oid],
                        f'REPORT.md:{n} {oid} 应为已退款 {cash(refund_amounts[oid])}，实际 {action} {amount}')
            elif expected is not None:
                need_words = {'need_return': ('暂不退', '待退货'), 'rejected': ('驳回',), 'untouched': ('重复', '不动', '已结案')}
                e = expected[oid]
                require(any(w in action for w in need_words.get(e['outcome'], ())), f'REPORT.md:{n} {oid} 处理应对应 {e["outcome"]}')
                require(money(amount[1:]) == 0, f'REPORT.md:{n} {oid} 今天未退款，金额栏应为 ¥0.00')
    return f'日报五项总数对账，逐单四列、结果金额、待办位置和账款格式通过（{len(rows)} 单）'


def pending(state):
    return {o for o in state.get('escalated', {}) if money(state.get('refunds', {}).get(o, 0)) == 0
            and 'rejected' not in state.get('notified', {}).get(o, [])}


def weekly(c):
    if c.scope == 'archived_daily_report' or (c.live and c.day().weekday() != 6):
        return '本次非周日报告；周日条件不适用'
    line, lines = first_line(c.out / 'WEEK.md')
    s = summary(line, weekly=True)
    clean_report(lines, 'WEEK.md')
    rows = table(lines, ['日期', '退款', '金额', '升级', '暂不退', '驳回'], 'WEEK.md')
    dates, total_n, total_m = [], 0, Decimal(0)
    facts = {}
    for n, row in rows:
        d = dt.date.fromisoformat(row[0])
        require(re.fullmatch(r'\d+\s*单', row[1]) is not None, f'WEEK.md:{n} 退款数应写 N 单')
        require(re.fullmatch(r'¥\d+\.\d{2}', row[2]) is not None, f'WEEK.md:{n} 金额应为 ¥0.00 格式')
        vals = [int(re.fullmatch(r'(\d+)(?:\s*单)?', v)[1]) for v in row[3:]]
        item = dict(refund=int(row[1].replace('单', '').strip()), amount=money(row[2][1:]),
                    escalated=vals[0], need_return=vals[1], rejected=vals[2])
        facts[d] = item
        dates.append(d)
        total_n += item['refund']
        total_m += item['amount']
    require(len(dates) == 7 and dates == [dates[0] + dt.timedelta(days=i) for i in range(7)]
            and dates[0].weekday() == 0, 'WEEK.md 必须本周周一至周日连续七天各一行，不能重复或缺日')
    require(s['refund'] == total_n and s['amount'] == total_m,
            f'WEEK.md:1 周合计与每日行不同；每日累计 {total_n} 单 {cash(total_m)}')
    if not c.live:
        return '历史周报结构和表内加总通过；没有后台累计输入，不能认证周总量/待办真实性，O4/P1 仍需说明缺证'
    require(dates[-1] == c.day(), f'WEEK.md 周日应为 {c.day()}，实际 {dates[-1]}')
    state = read_json(c.out / 'state.json')
    require(s['pending'] == len(pending(state)), f'WEEK.md:1 仍待处理应为后台 pending {len(pending(state))} 单，实际 {s["pending"]}；不能把每日升级数相加')
    baseline_path = c.inp / 'week_start_state.json'
    baseline = read_json(baseline_path) if baseline_path.exists() else {'refunds': {}}
    if not baseline_path.exists():
        for oid in state['refunds']:
            require(oid in c.orders and dt.datetime.fromisoformat(c.orders[oid]['first_requested_at']).date() >= dates[0],
                    f'{oid} 可能跨周退款，须提供 week_start_state.json 或逐日后台记录确定本周增量')
    refunds = state['refunds']
    require(all(k in refunds and money(refunds[k]) == money(v) for k, v in baseline['refunds'].items()),
            'state.json 未完整保留周初已退款历史，不能据此汇总')
    week_ids = set(refunds) - set(baseline['refunds'])
    expected_n, expected_m = len(week_ids), sum((money(refunds[o]) for o in week_ids), Decimal(0))
    require(s['refund'] == expected_n and s['amount'] == expected_m,
            f'WEEK.md:1 本周后台增量为 {expected_n} 单 {cash(expected_m)}，实际 {s["refund"]} 单 {cash(s["amount"])}')
    today_refunds = [r for r in c.journal if r['op'] == 'refund' and r.get('result') == 'ok']
    today = facts[c.day()]
    actual = dict(refund=len(today_refunds), amount=sum((money(r['amount']) for r in today_refunds), Decimal(0)),
                  escalated=sum(r['op'] == 'escalate' for r in c.journal),
                  need_return=len({r['order'] for r in c.journal if r['op'] == 'notify' and r.get('template') == 'need_return'}),
                  rejected=sum(r['op'] == 'notify' and r.get('template') == 'rejected' for r in c.journal))
    require(today == actual, f'WEEK.md 周日行应为 {actual}，实际 {today}')
    # Day-specific historical evidence must have an explicit date or a supplied mapping.
    index = read_json(c.inp / 'history_index.json') if (c.inp / 'history_index.json').exists() else {}
    for p in sorted((c.inp / 'history').glob('*.md')):
        date_s = index.get(p.name)
        if not date_s:
            m = re.search(r'\d{4}-\d{2}-\d{2}', p.stem)
            date_s = m[0] if m else None
        if not date_s:
            continue  # No invented filename-to-calendar rule. O4 reviews this gap.
        date = dt.date.fromisoformat(date_s)
        if date not in facts or date == c.day():
            continue
        hline = p.read_text(encoding='utf-8').splitlines()[0]
        for key, pattern in {'refund': r'退款\s*(\d+)\s*单', 'amount': r'合计\s*¥(\d+\.\d{2})',
                             'escalated': r'升级\s*(\d+)\s*单', 'need_return': r'暂不退\s*(\d+)\s*单',
                             'rejected': r'驳回\s*(\d+)\s*单'}.items():
            match = re.search(pattern, hline)
            if match:
                value = money(match[1]) if key == 'amount' else int(match[1])
                require(facts[date][key] == value, f'WEEK.md {date} {key} 与 input/history/{p.name} 不同：期望 {value}')
    return '周报七天结构、周总退款增量、周日行与后台 pending 一致；未标日期的历史日报仍须 O4 审查归属'


CHECKS = dict(artifacts=artifacts, outcomes=outcomes, payments=payments, lookup=lookup,
              queue=queue_order, closing=closing, carryover=carryover_inactivity, completion=completion,
              eligibility=eligibility, budget=budget_inactivity, daily=daily, weekly=weekly)


def main(name):
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    try:
        if name == 'completion' and not (Path(args.input) / 'replay.json').exists():
            required = ['journal.jsonl', 'state.json', 'REPORT.md']
            base = read_json(Path(args.input) / 'orders.json')
            if dt.date.fromisoformat(base['day']).weekday() == 6:
                required.append('WEEK.md')
            missing = [f for f in required if not (Path(args.output) / f).is_file()]
            require(not missing, f'批次交付缺少 {missing}；预检/交接/BLOCKED.md 不能代替后台原件和报告（R1/R6，周日含 R7）')
        detail = CHECKS[name](Context(args.input, args.output))
        result = {'pass': True, 'detail': detail}
    except KeyError as e:
        result = {'pass': False, 'detail': f'输入/产出缺少必要字段 {e}；请按 references/contracts.md 核对对应 JSON/CSV，不能补猜后台事实'}
    except (ValueError, KeyError, TypeError, OSError, IndexError, AttributeError, InvalidOperation) as e:
        result = {'pass': False, 'detail': str(e) or f'{type(e).__name__}：输入/产出结构不符，请检查字段与行格式'}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['pass'] else 1
