import React, { useState } from 'react'

/* HITL 审批卡片（v3.0 控制层）：自然语言文案 + 允许 / 拒绝 / 改成 60 秒 */

export default function ApprovalCard({ approval, onDecide }) {
  const [busy, setBusy] = useState('')
  if (!approval) return null
  const pending = approval.state === 'pending'

  async function decide(option) {
    setBusy(option.key)
    try {
      await onDecide(option.key, option.override_args)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className={'approval ' + (pending ? 'pending' : 'done')}>
      <div className="approval-head">
        <span className="approval-icon">🔐</span>
        <b>{approval.summary || `AI 想执行 ${approval.tool}，是否允许？`}</b>
        <span className="mono muted">{approval.tool} · {approval.trace_id}</span>
      </div>
      <div className="approval-actions">
        {(approval.options || []).map((o) => (
          <button
            key={o.key}
            disabled={!pending || busy}
            className={o.key === 'approve' ? '' : o.key === 'reject' ? 'danger' : 'ghost'}
            onClick={() => decide(o)}
          >
            {busy === o.key ? '提交中…' : o.label}
          </button>
        ))}
        {!pending && <span className="muted">已处理：{approval.decision}</span>}
      </div>
      {pending && (
        <p className="muted small">
          审批期间该工具调用会暂停等待；决策会写入审计哈希链。
        </p>
      )}
    </div>
  )
}
