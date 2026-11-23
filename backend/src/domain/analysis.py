from datetime import date
from math import exp, fsum, isfinite, lgamma, log, log1p


STITCH_PITCHES = ('3.0', '3.5', '4.0')
STAGE1_LABEL = '首检（第 1 次）'
STAGE2_LABEL = '补抽（第 2 次）'
COMBINED_LABEL = '两轮合并判定'

DECISION_LABELS = {
    'release': '证据达标，交主管复核',
    'investigate': '暂缓，排查工艺',
    'pending': '待定，可补抽一次',
    'hold': '暂缓，证据不足',
    'hold_after_supplement': '暂缓，补抽后证据仍不足',
}


def _identifier(row: dict, key: str, label: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label}不能为空。')
    return value.strip()


def _number(value, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label}必须为数值。')
    if not minimum <= value <= maximum or not isfinite(value):
        raise ValueError(f'{label}必须在 {minimum:g} 至 {maximum:g} 之间。')
    return float(value)


def _pitch(value) -> str:
    if value not in STITCH_PITCHES:
        raise ValueError('针距必须为 3.0、3.5 或 4.0 mm。')
    return value


def validate(row: dict) -> None:
    _identifier(row, 'batch_no', '工票批号')
    _identifier(row, 'specimen_id', '试片编号')
    _pitch(row.get('stitch_pitch'))
    _number(row.get('pull_force_n'), '拉脱峰值（N）', 0, 5000)
    tested_on = row.get('tested_on')
    try:
        if not isinstance(tested_on, str) or date.fromisoformat(tested_on).isoformat() != tested_on:
            raise ValueError
    except ValueError:
        raise ValueError('试验日期必须为有效日期，格式为 YYYY-MM-DD。') from None


def alpha_budget(confidence_pct: float, batch_count: int) -> float:
    """Per-ticket false-release budget shared by every review batch."""
    return (100 - confidence_pct) / (100 * batch_count)


def split_alphas(total: float, stage1_count: int, stage2_count: int) -> tuple[float, float]:
    """Pre-registered split of one ticket's budget between the two inspections.

    The split is proportional to each round's specimen count, so alpha1 + alpha2
    equals the original per-ticket budget and the union bound still caps the
    family-wise false-release probability.
    """
    if stage2_count <= 0:
        return total, 0.0
    share = stage1_count / (stage1_count + stage2_count)
    return total * share, total * (1 - share)


def _upper_tail(passed: int, total: int, probability: float) -> float:
    """Evaluate P(X >= passed) from the binomial probability mass function."""
    if passed == 0 or probability == 1:
        return 1.0
    if probability == 0:
        return 0.0
    if passed == total:
        return probability ** total

    log_factorial = lgamma(total + 1)
    log_pass = log(probability)
    log_fail = log1p(-probability)
    tail = fsum(
        exp(log_factorial - lgamma(count + 1) - lgamma(total - count + 1)
            + count * log_pass + (total - count) * log_fail)
        for count in range(passed, total + 1)
    )
    return min(1.0, tail)


def _lower_bound(passed: int, total: int, alpha: float) -> float:
    """Invert the upper tail to find the one-sided Clopper–Pearson bound."""
    if passed == 0:
        return 0.0
    if passed == total:
        return alpha ** (1 / total)

    low, high = 0.0, 1.0
    for _ in range(56):
        midpoint = (low + high) / 2
        if _upper_tail(passed, total, midpoint) < alpha:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2


def seed() -> list[dict]:
    lots = (
        ('BP-260810-A', '3.5', '2026-08-10', 27, ()),
        ('BP-260811-B', '3.5', '2026-08-11', 18, (365,)),
        ('BP-260812-C', '3.5', '2026-08-12', 6, ()),
        ('BP-260813-D', '3.0', '2026-08-13', 20, (372, 387)),
        ('BP-260814-E', '4.0', '2026-08-14', 12, (358, 376, 395)),
    )
    return [
        {
            'batch_no': batch_no,
            'specimen_id': f'{batch_no}-{index + 1:02d}',
            'stitch_pitch': pitch,
            'pull_force_n': failures[index] if index < len(failures) else 400 + index * 23 % 91,
            'tested_on': tested_on,
        }
        for batch_no, pitch, tested_on, total, failures in lots
        for index in range(total)
    ]


def _round_detail(label: str, rows: list[dict], force_limit: float, target: float, alpha: float) -> dict:
    total = len(rows)
    specimens = [
        {
            'specimen_id': row['specimen_id'].strip(),
            'pull_force_n': row['pull_force_n'],
            'tested_on': row['tested_on'],
            'passed': row['pull_force_n'] >= force_limit,
        }
        for row in rows
    ]
    passed = sum(item['passed'] for item in specimens)
    p_value = _upper_tail(passed, total, target) if total else 1.0
    return {
        'label': label,
        'total': total,
        'passed': passed,
        'observed_pct': round(100 * passed / total, 2) if total else 0.0,
        'p_value': p_value,
        'alpha': alpha,
        'lower_pct': round(100 * _lower_bound(passed, total, alpha), 2) if total else 0.0,
        'specimen_ids': [item['specimen_id'] for item in specimens],
        'specimens': specimens,
    }


def _decide(total: int, passed: int, target: float, alpha: float) -> str:
    if _upper_tail(passed, total, target) <= alpha:
        return 'release'
    if total and passed / total < target:
        return 'investigate'
    return 'pending'


def _pct(passed: int, total: int) -> str:
    return f'{100 * passed / total:.2f}%' if total else '—'


def _basis_line(label: str, detail: dict, alpha_symbol: str) -> str:
    return (
        f'{label} {detail["passed"]}/{detail["total"]} 片达标（实测 {_pct(detail["passed"], detail["total"])}），'
        f'精确 p 值 {detail["p_value"]:.6g}，与 {alpha_symbol} {detail["alpha"]:.6g} 比较'
    )


def _analyze_plan(by_id: dict, parameters: dict, pitch: str, force_limit: float,
                  target_pct: float, confidence_pct: float) -> dict:
    target = target_pct / 100
    batch_specs = parameters.get('batches') or []
    stage_map = parameters.get('stage_map') or {}
    if not batch_specs:
        raise ValueError('本次分析没有登记审查批次，请先建立抽样方案。')
    if len(batch_specs) > 100:
        raise ValueError('单次审查批次超过 100 批，请拆分方案。')
    for spec in batch_specs:
        if int(spec['stage1_count']) < 2 or int(spec['stage2_count']) < 2:
            raise ValueError(f'{spec["batch_no"]} 两次抽检都至少 2 片才能做精确检验。')
        expected = float(spec['alpha1']) + float(spec['alpha2'])
        if not isfinite(expected) or expected <= 0:
            raise ValueError(f'{spec["batch_no"]} 的两次检验阈值无效。')
    if 'alpha_total' in parameters:
        for spec in batch_specs:
            if abs(float(spec['alpha1']) + float(spec['alpha2']) - float(parameters['alpha_total'])) > 1e-12:
                raise ValueError(f'{spec["batch_no"]} 的两次检验阈值之和超出每批误放预算，方案已损坏。')

    results = []
    release_count = pending_count = 0
    used_ids = set()

    for spec in batch_specs:
        batch_no = str(spec['batch_no']).strip()
        stage1_count = int(spec['stage1_count'])
        stage2_count = int(spec['stage2_count'])
        alpha1, alpha2 = float(spec['alpha1']), float(spec['alpha2'])
        ids = stage_map.get(batch_no) or {}
        stage1_ids = list(ids.get('stage1') or [])
        stage2_ids = list(ids.get('stage2') or [])
        stage1_rows = [by_id[item] for item in stage1_ids if item in by_id]
        stage2_rows = [by_id[item] for item in stage2_ids if item in by_id]
        if len(stage1_rows) != stage1_count:
            raise ValueError(f'{batch_no} 首检试片应为 {stage1_count} 片，实际取到 {len(stage1_rows)} 片。')
        if stage2_rows and len(stage2_rows) != stage2_count:
            raise ValueError(f'{batch_no} 补抽试片还有 {stage2_count - len(stage2_rows)} 片未齐，暂不能合并判定。')
        for row in stage1_rows + stage2_rows:
            if row['stitch_pitch'] != pitch:
                raise ValueError(f'{batch_no} 有试片针距与方案 {pitch} mm 不一致。')
            if row['batch_no'].strip() != batch_no:
                raise ValueError(f'工票批号与方案不一致：{row["batch_no"]}。')

        stage1 = _round_detail(STAGE1_LABEL, stage1_rows, force_limit, target, alpha1)
        first_code = _decide(stage1['total'], stage1['passed'], target, alpha1)
        if first_code == 'pending' and stage2_count <= 0:
            first_code = 'hold'
        stage1['decision'] = first_code
        stage1['status'] = DECISION_LABELS[first_code]

        stage2 = None
        combined = None
        if stage2_rows:
            stage2 = _round_detail(STAGE2_LABEL, stage2_rows, force_limit, target, alpha2)
            stage2['decision'] = 'supplement'
            stage2['status'] = '已凑齐，合并重算'
            merged_rows = stage1_rows + stage2_rows
            combined = _round_detail(COMBINED_LABEL, merged_rows, force_limit, target, alpha2)
            combined_code = _decide(combined['total'], combined['passed'], target, alpha2)
            combined['decision'] = combined_code
            if combined_code == 'release':
                decision = 'release'
            elif combined_code == 'investigate':
                decision = 'investigate'
            else:
                decision = 'hold_after_supplement'
            combined['status'] = DECISION_LABELS[decision]
        else:
            decision = first_code

        judge = combined or stage1
        if decision == 'release':
            release_count += 1
        if decision == 'pending':
            pending_count += 1
        used_ids.update(stage1_ids)
        used_ids.update(stage2_ids)

        if combined:
            basis = (
                f'{_basis_line("首检", stage1, "α₁")}，首检结论为「{stage1["status"]}」；'
                f'补抽 {stage2["passed"]}/{stage2["total"]} 片达标后合并 {combined["passed"]}/{combined["total"]} 片，'
                f'合并 p 值 {combined["p_value"]:.6g} 与 α₂ {alpha2:.6g} 比较。'
                f'两轮阈值 α₁+α₂={alpha1 + alpha2:.6g}，仍受每批误放预算约束。'
            )
        else:
            basis = (
                f'{_basis_line("首检", stage1, "α₁")}；'
                + ('证据达标，交主管复核。' if decision == 'release'
                   else '实测达标率低于最低达标率。' if decision == 'investigate'
                   else '观测达标率不低但证据不足，可在台账补抽一次。' if decision == 'pending'
                   else '方案未安排补抽片数，证据不足只能暂缓。')
            )

        if combined:
            stage_label = COMBINED_LABEL
        elif stage2_count <= 0:
            stage_label = '首检（无补抽安排）'
        else:
            stage_label = '首检（第 1 次）'

        results.append({
            'batch_no': batch_no,
            'stage_label': stage_label,
            'decision': decision,
            'status': DECISION_LABELS[decision],
            'total': judge['total'],
            'passed': judge['passed'],
            'observed_pct': judge['observed_pct'],
            'lower_pct': judge['lower_pct'],
            'p_value': judge['p_value'],
            'alpha': judge['alpha'],
            'stage1': stage1,
            'stage2': stage2,
            'combined': combined,
            'stage1_ids': '、'.join(stage1['specimen_ids']),
            'stage2_ids': '、'.join(stage2['specimen_ids']) if stage2 else '—',
            'basis': basis,
        })

    batch_count = len(results)
    supplemented = sum(1 for row in results if row['combined'])
    total_specimens = len(used_ids)
    if supplemented:
        headline = (f'{pitch} mm 针距补抽复核后 {release_count}/{batch_count} 批证据达标'
                    f'，{batch_count - release_count} 批仍需处理')
    else:
        headline = (f'{pitch} mm 针距首检 {release_count}/{batch_count} 批证据达标'
                    f'，{pending_count} 批待定')
    metrics = [
        {'label': '归档工票批次', 'value': batch_count, 'unit': '批'},
        {'label': '纳入独立试片', 'value': total_specimens, 'unit': '片'},
        {'label': '证据达标批次', 'value': release_count, 'unit': '批'},
    ]
    if pending_count:
        metrics.append({'label': '仍待定批次', 'value': pending_count, 'unit': '批'})
    if supplemented:
        metrics.append({'label': '完成补抽批次', 'value': supplemented, 'unit': '批'})
    metrics.extend([
        {'label': '批次最低达标率', 'value': target_pct, 'unit': '%'},
        {'label': '每批误放预算 α_b', 'value': parameters.get('alpha_total', round(alpha_budget(confidence_pct, batch_count), 8))},
    ])
    return {
        'headline': headline,
        'summary': (
            f'按 {force_limit:g} N 划分试片达标，检验各批能否证明达标率高于 {target_pct:g}%。'
            f'本次审查 {batch_count} 批，每批误放预算 α_b=(1−{confidence_pct:g}%)/{batch_count}；'
            '首检与补抽的阈值 α₁、α₂ 按两轮片数预先分配，α₁+α₂=α_b，'
            '因此两次检验的整组误放概率仍不超过原上限。'
            '补抽只能在首检判为待定的工票上发起一次，凑齐后合并两轮试片重算。'
        ),
        'metrics': metrics,
        'columns': [
            {'key': 'batch_no', 'label': '工票批号'},
            {'key': 'stage_label', 'label': '判定阶段'},
            {'key': 'total', 'label': '判定试片数（片）'},
            {'key': 'passed', 'label': '达标数（片）'},
            {'key': 'observed_pct', 'label': '实测达标率（%）'},
            {'key': 'lower_pct', 'label': '单侧置信下界（%）'},
            {'key': 'p_value', 'label': '精确检验 p 值'},
            {'key': 'alpha', 'label': '本次判定阈值 α'},
            {'key': 'status', 'label': '工票处理建议'},
        ],
        'trace_columns': [
            {'key': 'stage1_ids', 'label': '首检试片号'},
            {'key': 'stage2_ids', 'label': '补抽试片号'},
            {'key': 'basis', 'label': '判定依据'},
        ],
        'rows': results,
        'chart': {
            'label': '各批判定单侧置信下界与最低达标率',
            'unit': '%',
            'points': [{'label': '最低达标率', 'value': target_pct}] + [
                {'label': row['batch_no'], 'value': row['lower_pct']} for row in results
            ],
        },
    }


def analyze(rows: list[dict], parameters: dict, observation_ids: list | None = None) -> dict:
    pitch = _pitch(parameters.get('stitch_pitch', '3.5'))
    force_limit = _number(parameters.get('force_limit_n', 400), '拉脱达标线（N）', 1, 5000)
    target_pct = _number(parameters.get('target_pct', 85), '批次最低达标率（%）', 1, 99.9)
    confidence_pct = _number(parameters.get('confidence_pct', 95), '整组置信水平（%）', 80, 99.9)

    if observation_ids is None:
        observation_ids = list(range(len(rows)))
    if len(observation_ids) != len(rows):
        raise ValueError('观测编号与记录数量不一致。')

    by_id = {}
    seen_specimens = set()
    for observation_id, row in zip(observation_ids, rows):
        validate(row)
        specimen_id = row['specimen_id'].strip()
        if specimen_id in seen_specimens:
            raise ValueError(f'试片编号重复：{specimen_id}。每片只可纳入一次。')
        seen_specimens.add(specimen_id)
        if observation_id in by_id:
            raise ValueError('同一试验记录被重复计入。')
        by_id[observation_id] = row

    return _analyze_plan(by_id, parameters, pitch, force_limit, target_pct, confidence_pct)
