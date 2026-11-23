import { download, get, post } from '../api/client.js';
import { bars, status, table } from '../components/common/data.js';
import { intro } from '../components/common/frame.js';
import { formError } from '../components/common/forms.js';
import { Decision, Role, RunKind, RunStatus, kindName } from '../constants/enums.js';
import { bindDownloads, bindForm, notify } from '../hooks/actions.js';
import { esc, formatMetric, timeLabel } from '../utils/html.js';
import { runTable } from './analysis.js';

function evidenceTable(result) {
  const rows = result.rows.filter(row => row.stage1);
  if (!rows.length) return '';
  return rows.map(row => {
    const stage1 = row.stage1;
    const stage2 = row.stage2;
    const combined = row.combined;
    return `<details class="evidence"><summary>${esc(row.batch_no)} · ${esc(row.status)}</summary>
      <div class="evidence-body">
        <h3>第 1 次抽检（首检）</h3>
        <p>试片 ${stage1.total} 片，达标 ${stage1.passed} 片；判定阈值 α₁=${esc(formatMetric(stage1.alpha))}；精确 p 值 ${esc(formatMetric(stage1.p_value))} → ${esc(stage1.status)}</p>
        <p class="ids">${esc(stage1.specimen_ids.join('、'))}</p>
        ${stage2 ? `<h3>第 2 次抽检（补抽）</h3>
          <p>试片 ${stage2.total} 片，达标 ${stage2.passed} 片；判定阈值 α₂=${esc(formatMetric(stage2.alpha))}；精确 p 值 ${esc(formatMetric(stage2.p_value))}</p>
          <p class="ids">${esc(stage2.specimen_ids.join('、'))}</p>` : ''}
        ${combined ? `<h3>合并判定</h3>
          <p>两轮合并 ${combined.total} 片，达标 ${combined.passed} 片；合并 p 值 ${esc(formatMetric(combined.p_value))} 与 α₂ 比较 → ${esc(combined.status)}</p>` : ''}
        <h3>凭什么判定</h3><p>${esc(row.basis)}</p>
      </div></details>`;
  }).join('');
}

export async function resultPage(spec, user, route) {
  if (!route.id) {
    const [runs, plans] = await Promise.all([get('/runs'), get('/plans')]);
    const planSection = plans.length ? `<section class="panel"><div class="panel-heading"><h2>抽样方案</h2></div>${table([
      {label:'方案',html: row => `<a href="#analysis/${row.id}">${esc(row.title)}</a>`},
      {label:'首检',html: row => row.first_run_id ? `<a href="#result/${row.first_run_id}">分析 #${row.first_run_id}</a>` : '—'},
    ], plans)}</section>` : '';
    return `${intro('结果与复核', spec.decision_prompt)}${planSection}<section class="panel"><div class="panel-heading"><h2>选择分析结果</h2></div>${runTable(runs, '暂无结果。分析员可先在「分析任务」建立方案并发起首检。')}</section>`;
  }
  const id = Number(route.id);
  if (!Number.isSafeInteger(id) || id <= 0) throw new Error('分析编号无效');
  const run = await get(`/runs/${id}`);
  const kind = run.kind === RunKind.SUPPLEMENT ? ` · ${kindName.supplement}` : (run.kind ? ` · ${kindName[run.kind]}` : '');
  const head = intro(run.title, `${run.sample_size} 条观测 · 快照末号 ${run.snapshot_id}${kind} · ${timeLabel(run.created_at)}`, status(run));
  if (run.status === RunStatus.QUEUED) return `${head}<div class="empty" data-pending="${id}">分析任务已入队，正在等待计算。此页会自动刷新。</div>`;
  if (run.status === RunStatus.FAILED) return `${head}<div class="empty" role="alert">${esc(run.error)} ${run.plan_id ? `<a href="#analysis/${run.plan_id}">回到方案</a>` : '<a href="#analysis">调整条件并重新计算</a>'}</div>`;
  const data = run.result;
  let review = '<p>等待复核负责人签核。签核后也可由只读角色查看。</p>';
  if (run.review) review = `<p><b>${run.review.decision === Decision.APPROVED ? '签核通过' : '退回补充'}</b> ${esc(run.review.note)}</p><small>${esc(run.review.reviewer)} · ${timeLabel(run.review.at)}</small>`;
  if (!run.review && user.role === Role.SUPERVISOR) review = `<form id="review-form" data-id="${id}"><label class="field"><span>复核结论</span><select name="decision"><option value="approved">签核通过</option><option value="returned">退回补充</option></select></label><label class="field"><span>复核依据</span><textarea name="note" required minlength="2" maxlength="1000" placeholder="${esc(spec.decision_prompt)}"></textarea></label>${formError}<button class="primary">保存复核</button></form>`;
  const parameters = spec.parameters.map(field => `<li><span>${esc(field.label)}</span><b>${esc(run.parameters[field.key])}</b></li>`).join('');
  const evidence = evidenceTable(data);
  return `${head}<div class="split result-summary"><section class="conclusion"><h2>${esc(data.headline)}</h2><p>${esc(data.summary)}</p>${data.metrics.length ? `<dl class="metrics">${data.metrics.map(metric => `<div><dt>${esc(metric.label)}</dt><dd>${esc(formatMetric(metric.value))}${metric.unit ? `<small> ${esc(metric.unit)}</small>` : ''}</dd></div>`).join('')}</dl>` : ''}</section><aside class="method"><h2>本次条件</h2><ul class="parameters">${parameters}</ul>${bars(data.chart)}</aside></div>
    <section class="panel"><div class="panel-heading"><h2>计算明细</h2><button data-download="/runs/${id}/export">下载 CSV（含试片号与依据）</button></div>${table(data.columns,data.rows,'当前参数下无明细，计算结论保留。')}</section>
    <section class="panel"><div class="panel-heading"><h2>抽检证据追溯</h2><span>每张工票两次各用了哪些试片、凭什么判定</span></div><div class="panel-body">${evidence || '<p>本次结果没有两阶段记录。</p>'}</div></section>
    <section class="panel"><div class="panel-heading"><h2>业务签核</h2>${run.review?.decision === Decision.APPROVED ? '<a href="#reports">查看分发 →</a>' : ''}</div><div class="panel-body">${review}</div></section>`;
}

export function wireResult(root, refresh) {
  bindDownloads(root, download);
  bindForm(root.querySelector('#review-form'), async form => {
    await post(`/runs/${form.dataset.id}/review`, Object.fromEntries(new FormData(form)));
    notify('复核记录已保存');
    refresh();
  });
  const pending = root.querySelector('[data-pending]');
  if (pending) setTimeout(() => {
    if (pending.isConnected && location.hash === `#result/${pending.dataset.pending}`) refresh();
  }, 800);
}
