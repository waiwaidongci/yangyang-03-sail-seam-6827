from collections import defaultdict
from datetime import date
from math import exp, fsum, isfinite, lgamma, log, log1p


STITCH_PITCHES = ('3.0', '3.5', '4.0')


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


def analyze(rows: list[dict], parameters: dict) -> dict:
    pitch = _pitch(parameters.get('stitch_pitch', '3.5'))
    force_limit = _number(parameters.get('force_limit_n', 400), '拉脱达标线（N）', 1, 5000)
    target_pct = _number(parameters.get('target_pct', 85), '批次最低达标率（%）', 1, 99.9)
    confidence_pct = _number(parameters.get('confidence_pct', 95), '整组置信水平（%）', 80, 99.9)
    target = target_pct / 100

    forces_by_batch = defaultdict(list)
    seen_specimens = set()
    for row in rows:
        validate(row)
        specimen_id = row['specimen_id'].strip()
        if specimen_id in seen_specimens:
            raise ValueError(f'试片编号重复：{specimen_id}。每片只可纳入一次。')
        seen_specimens.add(specimen_id)
        if row['stitch_pitch'] == pitch:
            forces_by_batch[row['batch_no'].strip()].append(row['pull_force_n'])
    if not forces_by_batch:
        raise ValueError(f'针距 {pitch} mm 暂无试片记录，请选择有记录的针距或补录试验。')

    # Bonferroni controls the chance of an erroneous release across the selected lots.
    alpha = (100 - confidence_pct) / (100 * len(forces_by_batch))
    results = []
    eligible_count = 0
    for batch_no, forces in sorted(forces_by_batch.items()):
        total = len(forces)
        passed = sum(force >= force_limit for force in forces)
        p_value = _upper_tail(passed, total, target)
        lower_pct = round(100 * _lower_bound(passed, total, alpha), 2)
        if p_value <= alpha:
            status = '证据达标，交主管复核'
            eligible_count += 1
        elif passed / total < target:
            status = '暂缓，排查工艺'
        else:
            status = '暂缓，证据不足'

        results.append({
            'batch_no': batch_no,
            'total': total,
            'passed': passed,
            'observed_pct': round(100 * passed / total, 2),
            'lower_pct': lower_pct,
            'p_value': p_value,
            'status': status,
        })

    batch_count = len(results)
    return {
        'headline': f'{pitch} mm 针距有 {eligible_count}/{batch_count} 批达到统计证据要求',
        'summary': (
            f'按 {force_limit:g} N 划分试片达标，检验各批能否证明达标率高于 {target_pct:g}%。'
            f'同次审查 {batch_count} 批，每批以 p ≤ {alpha:.8g} 判定。'
            '证据达标批次交主管核对工票，暂缓批次先排查工艺或按事先确定的方案补抽。'
            '每片须独立抽取并只记录一次，混合材料或夹具条件会削弱结论。'
        ),
        'metrics': [
            {'label': '归档工票批次', 'value': batch_count, 'unit': '批'},
            {'label': '纳入独立试片', 'value': sum(row['total'] for row in results), 'unit': '片'},
            {'label': '证据达标批次', 'value': eligible_count, 'unit': '批'},
            {'label': '批次最低达标率', 'value': target_pct, 'unit': '%'},
            {'label': '单批显著性阈值 α', 'value': alpha},
        ],
        'columns': [
            {'key': 'batch_no', 'label': '工票批号'},
            {'key': 'total', 'label': '试片数（片）'},
            {'key': 'passed', 'label': '达标数（片）'},
            {'key': 'observed_pct', 'label': '实测达标率（%）'},
            {'key': 'lower_pct', 'label': '单侧置信下界（%）'},
            {'key': 'p_value', 'label': '精确检验 p 值'},
            {'key': 'status', 'label': '工票处理建议'},
        ],
        'rows': results,
        'chart': {
            'label': '各批单侧置信下界与最低达标率',
            'unit': '%',
            'points': [{'label': '最低达标率', 'value': target_pct}] + [
                {'label': row['batch_no'], 'value': row['lower_pct']} for row in results
            ],
        },
    }
