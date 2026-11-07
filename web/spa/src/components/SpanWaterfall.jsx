import React, { useMemo, useState } from 'react'

/* 追踪瀑布图（v3.0 监视层）：自研 span 树 + 时间轴，默认只展示 4 个关键 span */

const KEY_SPANS = ['agent.run', 'llm.chat', 'tool.control_pump', 'guardrail.approval']

function depthOf(span, byId, guard = 0) {
  if (!span.parent_id || guard > 8) return 0
  const parent = byId[span.parent_id]
  return parent ? 1 + depthOf(parent, byId, guard + 1) : 0
}

export default function SpanWaterfall({ spans = [] }) {
  const [expanded, setExpanded] = useState(false)
  const rows = useMemo(() => {
    if (!spans.length) return []
    const byId = Object.fromEntries(spans.map((s) => [s.span_id, s]))
    const start = Math.min(...spans.map((s) => s.start_ts))
    const end = Math.max(...spans.map((s) => (s.end_ts || s.start_ts + s.duration_ms / 1000)))
    const total = Math.max(0.001, end - start)
    return spans.map((s) => ({
      ...s,
      depth: depthOf(s, byId),
      offset: ((s.start_ts - start) / total) * 100,
      width: Math.max(0.6, ((s.end_ts || s.start_ts + s.duration_ms / 1000) - s.start_ts) / total * 100),
    }))
  }, [spans])

  if (!rows.length) {
    return <p className="muted">暂无追踪数据（执行一次工作流或 Agent 任务后出现）</p>
  }

  const keyRows = rows.filter((r) => KEY_SPANS.includes(r.name))
  const visible = expanded || !keyRows.length ? rows : keyRows
  const hidden = rows.length - visible.length

  return (
    <div className="waterfall">
      <div className="wf-head">
        <span className="muted">span 树瀑布图 · {rows.length} 个 span</span>
        <button className="ghost small" onClick={() => setExpanded((v) => !v)}>
          {expanded ? '只看关键 4 个' : `显示全部${hidden > 0 ? `（另有 ${hidden} 个）` : ''}`}
        </button>
      </div>
      {visible.map((r) => {
        const tokens = r.attributes?.['gen_ai.usage.output_tokens']
        return (
          <div className="wf-row" key={r.span_id} style={{ paddingLeft: 8 + r.depth * 14 }}>
            <div className="wf-name mono" title={r.name}>
              <span className={'dot ' + (r.status === 'error' ? 'bad' : r.status === 'running' ? 'run' : 'ok')} />
              {r.name}
              {tokens ? <span className="badge">out {tokens} tok</span> : null}
            </div>
            <div className="wf-track">
              <div className={'wf-bar ' + (r.status === 'error' ? 'bad' : 'ok')}
                style={{ left: `${r.offset}%`, width: `${Math.max(2, r.width)}%` }} />
            </div>
            <div className="wf-ms mono">{Math.round(r.duration_ms)}ms</div>
          </div>
        )
      })}
    </div>
  )
}
