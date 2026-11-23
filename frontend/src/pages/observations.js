import { download, get, importFile, post } from '../api/client.js';
import { table } from '../components/common/data.js';
import { intro } from '../components/common/frame.js';
import { fieldControl, formError } from '../components/common/forms.js';
import { Role, SupplementStatus, supplementName } from '../constants/enums.js';
import { bindDownloads, bindForm, notify } from '../hooks/actions.js';
import { formValues } from '../types/form.js';
import { esc } from '../utils/html.js';

const specimenFields = ['specimen_id', 'pull_force_n', 'tested_on'];

function supplementPanel(supplement, spec, candidates, writable) {
  if (!supplement) return '';
  const {status, filled_count, stage2_count, batch_no, remaining} = supplement;
  const locked = status === SupplementStatus.OPEN && writable;
  const fields = spec.fields.filter(field => specimenFields.includes(field.key));
  const hidden = `<input type="hidden" name="batch_no" value="${esc(supplement.batch_no)}">
    <input type="hidden" name="stitch_pitch" value="${esc(supplement.stitch_pitch)}">`;
  const statusText = supplementName[status] || status;
  const selectable = candidates.filter(item => !item.attached);
  let body = `<p><b>${esc(batch_no)}</b> · ${esc(supplement.stitch_pitch)} mm · 补抽（第 2 次）已录 ${filled_count}/${stage2_count} 片，还差 ${esc(remaining)} 片 · 状态：${esc(statusText)}</p>`;
  if (locked) {
    if (selectable.length) {
      body += `<form id="supplement-select" data-id="${supplement.id}">
        <p>台账里已有本工票、首检快照之后登记的试片。勾选后一次并入补抽：</p>
        <div class="table-wrap"><table><thead><tr><th scope="col">选择</th><th scope="col">试片编号</th><th scope="col">拉脱峰值（N）</th><th scope="col">试验日期</th></tr></thead><tbody>
        ${selectable.map(item => `<tr><td><input type="checkbox" name="pick" value="${item.id}"></td><td>${esc(item.specimen_id)}</td><td>${esc(item.pull_force_n)}</td><td>${esc(item.tested_on)}</td></tr>`).join('')}
        </tbody></table></div>${formError}<button class="primary">并入所选补抽试片</button></form>`;
    }
    body += `<form id="supplement-form" data-id="${supplement.id}">${hidden}
      <p><b>或直接录入一片新试片</b>（首检快照之后登记，片号不可与首检重复）：</p>
      <div class="form-grid">${fields.map(field => fieldControl(field)).join('')}</div>
      ${formError}<button class="primary">录入一片补抽试片</button></form>`;
  } else if (status === SupplementStatus.OPEN) {
    body += '<p>补抽已开放，等待质检员录入试片。</p>';
  } else if (status === SupplementStatus.FAILED) {
    body += `<p role="alert">${esc(supplement.run_error || '合并重算失败')}</p>`;
    if (writable) body += `<button data-retry="${supplement.id}">重试合并重算（不重复计片）</button>`;
  } else if (status === SupplementStatus.READY) {
    body += '<p>试片已凑齐，正在排队重算。</p>';
  } else if (status === SupplementStatus.QUEUED) {
    body += '<p>试片已凑齐，后台正在合并两轮试片重算。此页会自动刷新。</p>';
  } else if (status === SupplementStatus.COMPLETED && supplement.run_id) {
    body += `<p>合并判定已完成：<a href="#result/${supplement.run_id}">查看结果 #${supplement.run_id}</a></p>`;
  }
  const rows = [...supplement.specimens].sort((a, b) => a.specimen_id.localeCompare(b.specimen_id));
  const tableHtml = rows.length ? table([{key:'specimen_id',label:'已并入试片号'},{key:'pull_force_n',label:'拉脱峰值（N）'},{key:'tested_on',label:'试验日期'}], rows) : '';
  const pendingRefresh = status === SupplementStatus.QUEUED ? ` data-pending-supplement="${supplement.id}"` : '';
  return `<section class="panel supplement"${pendingRefresh}><div class="panel-heading"><h2>${writable ? '补抽录入' : '补抽进度'} · ${esc(batch_no)}</h2><span class="status">${esc(statusText)}</span></div>
    <div class="panel-body">${body}</div>${tableHtml}</section>`;
}

export async function observationPage(spec, user, route) {
  const offset = Math.max(0, Number.parseInt(route.id, 10) || 0);
  const writable = user.role !== Role.VIEWER;
  const [{total, items}, supplements] = await Promise.all([
    get(`/observations?offset=${offset}&limit=20`),
    get('/supplements'),
  ]);
  const active = supplements.filter(item => ['open', 'ready', 'queued', 'failed'].includes(item.status)).slice(0, 3);
  const candidates = await Promise.all(active.map(item =>
    writable && item.status === 'open' ? get(`/supplements/${item.id}/candidates`) : Promise.resolve([])));
  return `${intro('数据台账', spec.source, `<span class="count">${total} <small>条${esc(spec.record_name)}</small></span>`)}
    ${writable ? `<div class="tools"><details><summary>登记一条${esc(spec.record_name)}</summary><form id="record-form"><div class="form-grid">${spec.fields.map(field => fieldControl(field)).join('')}</div>${formError}<button class="primary">保存记录</button></form></details>
    <details><summary>按模板导入 CSV</summary><form id="import-form"><p>使用 UTF-8 CSV，每次最多 500 条。重复行自动跳过。</p><button type="button" data-download="/observations/template">下载模板</button><label class="field"><span>CSV 文件</span><input type="file" name="file" accept=".csv,text/csv" required></label>${formError}<button class="primary">导入文件</button></form></details></div>` : ''}
    ${active.map((item, index) => supplementPanel(item, spec, candidates[index], writable)).join('')}
    <section class="panel"><div class="panel-heading"><h2>${esc(spec.record_name)}明细</h2>${writable ? '<a class="text-link" href="#analysis">发起分析 →</a>' : ''}</div>
    ${table([{key:'id',label:'记录号'},...spec.fields], items.map(item => ({id:item.id,...item.data})), '暂无观测。分析员可先导入 CSV 或登记样本。')}
    ${total ? `<div class="pagination"><span>第 ${offset + 1}–${Math.min(total,offset + 20)} 条</span>${offset > 0 ? `<a href="#observations/${Math.max(0, offset-20)}">上一页</a>` : ''}${offset+20 < total ? `<a href="#observations/${offset+20}">下一页</a>` : ''}</div>` : ''}</section>`;
}

export function wireObservations(root, spec, refresh) {
  bindDownloads(root, download);
  bindForm(root.querySelector('#record-form'), async form => {
    await post('/observations', formValues(form, spec.fields));
    notify('记录已保存');
    if (location.hash === '#observations' || !location.hash) refresh();
    else location.hash = '#observations';
  });
  bindForm(root.querySelector('#import-form'), async form => {
    const report = await importFile(form.elements.file.files[0]);
    notify(`已导入 ${report.added} 条 · 跳过 ${report.skipped} 条重复记录`);
    refresh();
  });
  bindForm(root.querySelector('#supplement-form'), async form => {
    const supplementId = form.dataset.id;
    const values = formValues(form, spec.fields);
    const report = await post(`/supplements/${supplementId}/specimens`, {records: [values]});
    notify(`补抽已录 ${report.filled_count}/${report.stage2_count} 片`);
    refresh();
  });
  bindForm(root.querySelector('#supplement-select'), async form => {
    const ids = [...form.querySelectorAll('input[name="pick"]:checked')].map(input => Number(input.value));
    if (!ids.length) throw new Error('请先勾选要并入的试片');
    const report = await post(`/supplements/${form.dataset.id}/specimens`, {observation_ids: ids});
    notify(`补抽已录 ${report.filled_count}/${report.stage2_count} 片`);
    refresh();
  });
  root.querySelectorAll('[data-retry]').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      await post(`/supplements/${button.dataset.retry}/retry`, {});
      notify('已重新排队合并重算');
      refresh();
    } catch (err) {
      notify(err.message, true);
      button.disabled = false;
    }
  }));
  const pending = root.querySelector('[data-pending-supplement]');
  if (pending) setTimeout(() => {
    if (pending.isConnected && location.hash.startsWith('#observations')) refresh();
  }, 1200);
}
