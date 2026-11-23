import { get, post } from '../api/client.js';
import { intro } from '../components/common/frame.js';
import { status, table } from '../components/common/data.js';
import { fieldControl, formError } from '../components/common/forms.js';
import { Role } from '../constants/enums.js';
import { bindForm, notify } from '../hooks/actions.js';
import { formValues } from '../types/form.js';
import { esc, timeLabel } from '../utils/html.js';

export function runTable(runs, message) {
  return table([
    {label:'分析名称',html: row => `<a href="#result/${row.id}">${esc(row.title)}</a>`},
    {label:'观测条数',key:'sample_size'}, {label:'状态',html:status},
    {label:'提交时间',html:row => timeLabel(row.created_at)},
  ], runs, message);
}

function planTable(plans) {
  return table([
    {label:'方案',html: row => `<a href="#analysis/${row.id}">${esc(row.title)}</a>`},
    {label:'审查批次',html: row => `${row.batches.length} 批`},
    {label:'首检',html: row => row.first_run_id ? `<a href="#result/${row.first_run_id}">分析 #${row.first_run_id}</a>` : '—'},
    {label:'建立时间',html: row => timeLabel(row.created_at)},
  ], plans, '还没有抽样方案。首检前先建立方案，登记审查批次和两次抽检片数。');
}

function batchRow(index) {
  return `<div class="batch-row"><span>${index + 1}</span>
      <label class="field"><span>工票批号</span><input name="batch_no_${index}" required maxlength="96" placeholder="BP-260812-C"></label>
      <label class="field"><span>首检片数</span><input name="stage1_${index}" type="number" min="2" max="200" required value="6"></label>
      <label class="field"><span>补抽片数</span><input name="stage2_${index}" type="number" min="2" max="200" required value="6"></label>
    </div>`;
}

function batchRows(count) {
  return `<div class="batch-rows" data-rows>${Array.from({length: count}, (_, index) => batchRow(index)).join('')}</div>`;
}

function planDetail(plan) {
  if (!plan) return '';
  const parameters = spec.parameters.map(field => `<li><span>${esc(field.label)}</span><b>${esc(plan.parameters[field.key])}</b></li>`).join('');
  const rows = plan.batches.map(batch => {
    let action = '—';
    const supplement = batch.supplement;
    if (supplement?.status === 'completed' && supplement.run_id) {
      action = `<a href="#result/${supplement.run_id}">合并结果 #${supplement.run_id}</a>`;
    } else if (supplement) {
      action = `<a href="#observations">台账补抽 #${supplement.id}</a>（${supplement.filled_count}/${supplement.stage2_count}）`;
    } else if (batch.supplement_available) {
      action = `<button data-open-supplement="${esc(batch.batch_no)}" data-plan="${plan.id}">发起补抽</button>`;
    } else if (batch.first_decision === 'release') {
      action = '已达标';
    } else if (batch.first_decision) {
      action = '不开放补抽';
    }
    return `<tr><td>${esc(batch.batch_no)}</td><td>${batch.stage1_count}</td><td>${batch.stage2_count}</td>
      <td>${batch.alpha1.toPrecision(4)}</td><td>${batch.alpha2.toPrecision(4)}</td>
      <td>${esc(batch.first_status)}</td><td>${action}</td></tr>`;
  }).join('');
  return `<section class="panel"><div class="panel-heading"><h2>方案明细 · ${esc(plan.title)}</h2>
      ${plan.first_run_id ? `<a class="text-link" href="#result/${plan.first_run_id}">查看首检结果 →</a>` : `<button data-first-run="${plan.id}">核对无误，发起首检</button>`}</div>
    <div class="panel-body"><ul class="parameters">${parameters}</ul>
    <p class="aside-note">每批误放预算 α_b = (1−置信水平)/批数 = ${plan.alpha_total.toPrecision(4)}；两次检验的阈值按片数预先分配，α₁+α₂=α_b。</p></div>
    <div class="table-wrap"><table><thead><tr><th>工票批号</th><th>首检片数</th><th>补抽片数</th><th>α₁</th><th>α₂</th><th>首检结论</th><th>补抽</th></tr></thead><tbody>${rows}</tbody></table></div>
    </section>`;
}

export async function analysisPage(spec, user, route) {
  const [plans, runs] = await Promise.all([get('/plans'), get('/runs')]);
  const selected = route.id ? plans.find(plan => plan.id === Number(route.id)) : null;
  const form = user.role === Role.ANALYST ? `
    <form id="plan-form" class="panel-body" data-rows-count="3">
      <label class="field"><span>方案名称</span><input name="title" required maxlength="120" value="${esc(spec.direction)}复核"></label>
      <div class="form-grid">${spec.parameters.map(parameter => fieldControl(parameter, true)).join('')}</div>
      <p><b>审查批次</b>：首检前定好每张工票两次抽检的片数。判为待定的工票才开放一次补抽。</p>
      ${batchRows(3)}
      <button type="button" data-add-batch>再加一批</button>
      <label class="check"><input type="checkbox" name="run_first" checked> 建立后立即发起首检（取消勾选可先保存方案，核对台账后再发起）</label>
      ${formError}<button class="primary">保存方案</button>
    </form>` : '<p class="panel-body">由业务分析员建立抽样方案并发起首检。此账号可查看方案与结果。</p>';
  return `${intro('分析任务', spec.algorithm)}
    <div class="split"><section class="panel"><div class="panel-heading"><h2>抽样方案</h2></div>${form}</section>
    <aside class="method"><h2>计算口径</h2><p>${esc(spec.formula)}</p><p class="aside-note">方案建立时固化审查批次、达标线和两次抽检片数。首检与补抽的阈值预先分配，两次检验合起来仍受原误放上限约束。</p></aside></div>
    ${planDetail(selected)}
    <section class="panel"><div class="panel-heading"><h2>历史方案</h2></div>${planTable(plans)}</section>
    <section class="panel"><div class="panel-heading"><h2>历史分析</h2></div>${runTable(runs, '还没有可查看的分析。发起首检后可在这里追踪。')}</section>`;
}

function collectBatches(form) {
  const count = Number(form.dataset.rowsCount || 3);
  const batches = [];
  for (let index = 0; index < count; index += 1) {
    const batchNo = form.elements[`batch_no_${index}`];
    if (!batchNo || !batchNo.value.trim()) continue;
    batches.push({
      batch_no: batchNo.value.trim(),
      stage1_count: Number(form.elements[`stage1_${index}`].value),
      stage2_count: Number(form.elements[`stage2_${index}`].value),
    });
  }
  return batches;
}

export function wireAnalysis(root, spec, refresh) {
  bindForm(root.querySelector('#plan-form'), async form => {
    const batches = collectBatches(form);
    if (!batches.length) throw new Error('请至少登记一张工票');
    const created = await post('/plans', {
      title: form.elements.title.value,
      parameters: formValues(form, spec.parameters),
      batches,
      run_first: form.elements.run_first.checked,
    });
    if (created.run_id) location.hash = `#result/${created.run_id}`;
    else {
      notify('方案已保存。核对台账后可在方案明细发起首检。');
      location.hash = `#analysis/${created.plan.id}`;
      refresh();
    }
  });
  root.querySelector('[data-add-batch]')?.addEventListener('click', () => {
    const form = root.querySelector('#plan-form');
    const count = Number(form.dataset.rowsCount || 3);
    form.dataset.rowsCount = String(count + 1);
    form.querySelector('[data-rows]').insertAdjacentHTML('beforeend', batchRow(count));
  });
  root.querySelectorAll('[data-first-run]').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      await post(`/plans/${button.dataset.firstRun}/first-run`, {});
      notify('首检已发起，后台正在计算');
      refresh();
    } catch (err) {
      notify(err.message, true);
      button.disabled = false;
    }
  }));
  root.querySelectorAll('[data-open-supplement]').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      await post('/supplements', {plan_id: Number(button.dataset.plan), batch_no: button.dataset.openSupplement});
      notify('补抽已开放，请到台账录入试片');
      refresh();
    } catch (err) {
      notify(err.message, true);
      button.disabled = false;
    }
  }));
}
