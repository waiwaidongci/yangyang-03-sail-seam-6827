export const Role = Object.freeze({ VIEWER: 'viewer', ANALYST: 'analyst', SUPERVISOR: 'supervisor' });
export const RunStatus = Object.freeze({ QUEUED: 'queued', SUCCEEDED: 'succeeded', FAILED: 'failed' });
export const RunKind = Object.freeze({ FIRST: 'first', SUPPLEMENT: 'supplement' });
export const SupplementStatus = Object.freeze({ OPEN: 'open', READY: 'ready', QUEUED: 'queued', COMPLETED: 'completed', FAILED: 'failed' });
export const Decision = Object.freeze({ APPROVED: 'approved', RETURNED: 'returned' });
export const roleName = {viewer: '只读查看', analyst: '业务分析员', supervisor: '复核负责人'};
export const statusName = {queued: '等待计算', succeeded: '等待复核', failed: '计算失败', approved: '已签核', returned: '已退回'};
export const supplementName = {open: '待补抽', ready: '已凑齐', queued: '合并重算中', completed: '已合并判定', failed: '重算失败'};
export const kindName = {first: '首检', supplement: '补抽合并'};
export const decisionName = {
  release: '证据达标，交主管复核',
  investigate: '暂缓，排查工艺',
  pending: '待定，可补抽一次',
  hold: '暂缓，证据不足',
  hold_after_supplement: '暂缓，补抽后证据仍不足',
};
