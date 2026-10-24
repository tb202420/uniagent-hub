import React, { useEffect, useMemo, useState } from 'react'
import { ReactFlow, Background, Controls, MiniMap } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { getJSON } from '../api.js'

// 依赖深度分层布局（初版手工布局；ELK 自动布局为下一步计划）
function layout(steps) {
  const byId = Object.fromEntries(steps.map((s) => [s.id, s]))
  const depth = {}
  function d(id, seen = new Set()) {
    if (id in depth) return depth[id]
    if (seen.has(id)) return 0
    seen.add(id)
    const s = byId[id]
    depth[id] = s ? Math.max(0, ...(s.depends_on || []).map((x) => d(x, seen) + 1)) : 0
    return depth[id]
  }
  steps.forEach((s) => d(s.id))
  const nodes = steps.map((s) => ({
    id: s.id,
    position: { x: 120 + depth[s.id] * 230, y: 60 + (s.id.charCodeAt(0) % 7) * 80 },
    data: { label: `${s.id}\n${s.tool}${s.condition ? '\n⇢ 条件' : ''}` },
    style: { fontSize: 11, whiteSpace: 'pre-line' },
  }))
  const edges = steps.flatMap((s) =>
    (s.depends_on || []).map((dep) => ({
      id: `${dep}->${s.id}`, source: dep, target: s.id, animated: true,
    })))
  return { nodes, edges }
}

export default function WorkflowPage() {
  const [defs, setDefs] = useState([])
  const [selected, setSelected] = useState('')
  const [runs, setRuns] = useState([])

  useEffect(() => {
    getJSON('/api/workflow-defs').then((d) => {
      setDefs(d.items)
      if (d.items.length) setSelected(d.items[0].name)
    }).catch(() => setDefs([]))
    getJSON('/api/workflows').then((d) => setRuns(d.items.slice(0, 10))).catch(() => setRuns([]))
  }, [])

  const def = defs.find((d) => d.name === selected)
  const flow = useMemo(() => (def ? layout(def.steps) : { nodes: [], edges: [] }), [def])

  return (
    <section>
      <div className="bar">
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {defs.length === 0 && <option value="">（Hub 未启动或无蓝图）</option>}
          {defs.map((d) => <option key={d.name} value={d.name}>{d.name}（{d.steps.length} 步）</option>)}
        </select>
        <span className="muted">蓝图 DAG 可视化 · 最近执行 {runs.length} 条</span>
      </div>
      {def && (
        <div className="flow">
          <ReactFlow nodes={flow.nodes} edges={flow.edges} fitView>
            <Background /><Controls /><MiniMap pannable zoomable />
          </ReactFlow>
        </div>
      )}
      <table>
        <thead><tr><th>工作流</th><th>结果</th><th>trace</th><th>步骤数</th></tr></thead>
        <tbody>
          {runs.map((r, i) => (
            <tr key={i}>
              <td className="mono">{r.workflow}</td>
              <td className={r.ok ? 'ok' : 'bad'}>{r.ok ? 'ok' : 'failed'}</td>
              <td className="mono">{r.trace_id}</td>
              <td>{(r.steps || []).length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
