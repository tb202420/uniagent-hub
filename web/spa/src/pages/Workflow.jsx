import React, { useEffect, useMemo, useState } from 'react'
import { ReactFlow, Background, Controls, MiniMap } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { getJSON } from '../api.js'

/* 依赖深度分层（ELK 不可用时的回落布局） */
function layeredLayout(steps) {
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
  return {
    nodes: steps.map((s) => ({
      id: s.id,
      position: { x: 40 + depth[s.id] * 220, y: 40 + (s.id.charCodeAt(0) % 7) * 80 },
      data: { label: `${s.id}\n${s.tool}${s.condition ? '\n⇢ 条件' : ''}` },
      style: { fontSize: 11, whiteSpace: 'pre-line' },
    })),
    edges: steps.flatMap((s) => (s.depends_on || []).map((dep) => ({
      id: `${dep}->${s.id}`, source: dep, target: s.id, animated: true }))),
  }
}

/* ELK 自动布局（v2.0 §3.2：layered + RIGHT 方向） */
async function elkLayout(steps) {
  const ELK = (await import('elkjs')).default
  const elk = new ELK()
  const graph = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.spacing.nodeNode': '40',
      'elk.layered.spacing.nodeNodeBetweenLayers': '90',
    },
    children: steps.map((s) => ({
      id: s.id, width: 170, height: 46,
      labels: [{ text: `${s.id} · ${s.tool}` }],
    })),
    edges: steps.flatMap((s) => (s.depends_on || []).map((dep, i) => ({
      id: `${dep}->${s.id}`, sources: [dep], targets: [s.id],
    }))),
  }
  const out = await elk.layout(graph)
  return {
    nodes: out.children.map((n) => ({
      id: n.id,
      position: { x: n.x, y: n.y },
      data: { label: n.labels?.[0]?.text || n.id },
      style: { fontSize: 11 },
    })),
    edges: steps.flatMap((s) => (s.depends_on || []).map((dep) => ({
      id: `${dep}->${s.id}`, source: dep, target: s.id, animated: true }))),
  }
}

export default function WorkflowPage() {
  const [defs, setDefs] = useState([])
  const [selected, setSelected] = useState('')
  const [runs, setRuns] = useState([])
  const [flow, setFlow] = useState({ nodes: [], edges: [] })
  const [engineLabel, setEngineLabel] = useState('')

  useEffect(() => {
    getJSON('/api/workflow-defs').then((d) => {
      setDefs(d.items)
      if (d.items.length) setSelected(d.items[0].name)
    }).catch(() => setDefs([]))
    getJSON('/api/workflows').then((d) => setRuns(d.items.slice(0, 10))).catch(() => setRuns([]))
  }, [])

  const def = defs.find((d) => d.name === selected)

  useEffect(() => {
    if (!def) return
    let cancelled = false
    elkLayout(def.steps).then((f) => {
      if (!cancelled) { setFlow(f); setEngineLabel('ELK layered') }
    }).catch(() => {
      if (!cancelled) {
        setFlow(layeredLayout(def.steps))
        setEngineLabel('依赖深度分层（ELK 回落）')
      }
    })
    return () => { cancelled = true }
  }, [def])

  return (
    <section>
      <div className="bar">
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {defs.length === 0 && <option value="">（Hub 未启动或无蓝图）</option>}
          {defs.map((d) => (
            <option key={d.name} value={d.name}>
              {d.name}（{d.steps.length} 步{d.parallel ? ' · 并行' : ''}）
            </option>
          ))}
        </select>
        <span className="muted">布局：{engineLabel || '…'} · 最近执行 {runs.length} 条</span>
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
