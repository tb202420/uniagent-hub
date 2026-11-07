import React, { useCallback, useEffect, useRef, useState } from 'react'
import { getJSON } from '../api.js'
import { useEventStream } from '../hooks/useEventStream.js'
import { useRafTokens } from '../hooks/useRafTokens.js'
import SpanWaterfall from '../components/SpanWaterfall.jsx'
import ApprovalCard from '../components/ApprovalCard.jsx'

/* 监视层：Model Output Console（流式 token + 四阶段状态条 + 追踪瀑布图） */

const STAGES = [
  { key: 'identified', label: '识别' },
  { key: 'executing', label: '执行中' },
  { key: 'result', label: '结果' },
  { key: 'error', label: '错误' },
]

export default function ConsolePage() {
  const { text, push, reset, flushFrames } = useRafTokens()
  const [source, setSource] = useState('')
  const [stages, setStages] = useState({})
  const [spanMap, setSpanMap] = useState({})
  const [approval, setApproval] = useState(null)
  const [status, setStatus] = useState('idle')
  const activeTrace = useRef('')

  useEffect(() => {
    getJSON('/api/traces').then((d) => {
      const latest = (d.items || [])[0]
      if (latest) {
        const map = {}
        latest.spans.forEach((s) => { map[s.span_id] = s })
        activeTrace.current = latest.trace_id
        setSpanMap(map)
      }
    }).catch(() => {})
    getJSON('/api/hitl/pending').then((d) => {
      if ((d.items || []).length) setApproval(d.items[0])
    }).catch(() => {})
  }, [])

  useEventStream(useCallback((e) => {
    if (e.kind === '__status') { setStatus(e.status); return }
    if (e.kind === 'agent.token') {
      setSource(`${e.source || 'agent'}${e.model ? ` · ${e.model}` : ''}`)
      push(e.delta || '')
    } else if (e.kind === 'tool.stage') {
      const key = `${e.trace_id}:${e.tool}`
      setStages((prev) => ({
        ...prev,
        [key]: { ...(prev[key] || {}), [e.stage]: true, latency: e.latency_ms,
          trace: e.trace_id, tool: e.tool, message: e.message },
      }))
    } else if (e.kind === 'span.start' || e.kind === 'span.end') {
      const s = e.span
      // 只保留同一条 trace 的 span，避免与上一条 trace 混在一起画瀑布图
      setSpanMap((prev) => {
        if (s.trace_id !== activeTrace.current) {
          activeTrace.current = s.trace_id
          return { [s.span_id]: s }
        }
        return { ...prev, [s.span_id]: s }
      })
    } else if (e.kind === 'hitl.request') {
      setApproval(e.approval)
    } else if (e.kind === 'hitl.decision') {
      setApproval((prev) => (prev?.approval_id === e.approval.approval_id ? e.approval : prev))
    }
  }, [push]))

  const spans = Object.values(spanMap).sort((a, b) => a.start_ts - b.start_ts)
  const stageRows = Object.values(stages).slice(-8)

  async function decide(decision, overrideArgs) {
    if (!approval) return
    await fetch('/api/hitl/decide', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        approval_id: approval.approval_id,
        decision: decision === 'approve' ? 'approved' : decision === 'reject' ? 'rejected' : 'modify',
        override_args: overrideArgs,
        decided_by: 'monitor-console',
      }),
    })
  }

  return (
    <section>
      <div className="bar">
        <span className={'ws ' + status}>{status === 'open' ? '事件流已连接' : status}</span>
        <span className="muted">模型输出监视台 · RAF 批处理（已 flush {flushFrames} 帧）</span>
        <button className="ghost" onClick={reset}>清空输出</button>
      </div>

      {approval && <ApprovalCard approval={approval} onDecide={decide} />}

      <div className="console-grid">
        <div className="panel">
          <h3>模型输出（流式）<span className="badge">{source || '等待 Agent 输出'}</span></h3>
          <pre className="stream">{text || '（尚无 token 增量）'}</pre>
          {!text && (
            <p className="muted small">
              提示：无 LLM Key 时展示确定性脚本 Agent 的输出（source 会标注 script-agent，
              不会冒充模型）。
            </p>
          )}
        </div>

        <div className="panel">
          <h3>工具调用四阶段</h3>
          {!stageRows.length && <p className="muted small">等待工具调用…</p>}
          {stageRows.map((r) => (
            <div className="stage-row" key={`${r.trace}:${r.tool}`}>
              <div className="mono">{r.tool}<span className="muted small"> · {r.trace}</span></div>
              <div className="stage-chips">
                {STAGES.map((s) => (
                  <span key={s.key}
                    className={'stage ' + (r[s.key] ? (s.key === 'error' ? 'bad' : 'ok') : 'idle')}>
                    {s.label}
                  </span>
                ))}
                {r.latency ? <span className="muted small">{r.latency}ms</span> : null}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3>追踪瀑布图（OTel GenAI SemConv）</h3>
        <SpanWaterfall spans={spans} />
      </div>
    </section>
  )
}
