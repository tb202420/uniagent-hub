import React, { useCallback, useState } from 'react'
import { getJSON } from '../api.js'
import { useEventStream } from '../hooks/useEventStream.js'
import ApprovalCard from '../components/ApprovalCard.jsx'

/* 编排层（简易模式）：问题陈述 + 场景卡片 → HITL 审批 → 执行 → 步骤进度 */

const HERO_QUESTION = '我想让 AI 帮我浇花，但我不放心它直接动手。点这里看它怎么先问我。'

export default function ScenesPage() {
  const [scenes, setScenes] = useState([])
  const [active, setActive] = useState(null)
  const [params, setParams] = useState({})
  const [running, setRunning] = useState(false)
  const [steps, setSteps] = useState([])
  const [result, setResult] = useState(null)
  const [trace, setTrace] = useState('')
  const [approval, setApproval] = useState(null)

  React.useEffect(() => {
    getJSON('/api/scenes').then((d) => setScenes(d.items)).catch(() => setScenes([]))
  }, [])

  useEventStream(useCallback((e) => {
    if (e.kind === 'step') {
      if (!trace || e.wf === trace) setSteps((prev) => [...prev.slice(-40), e])
    } else if (e.kind === 'hitl.request') {
      setApproval(e.approval)
    } else if (e.kind === 'hitl.decision') {
      setApproval((prev) => (prev?.approval_id === e.approval.approval_id ? e.approval : prev))
    }
  }, [trace]))

  function open(scene) {
    setActive(scene)
    setParams({ ...(scene.params || {}) })
    setSteps([]); setResult(null); setApproval(null); setTrace('')
  }

  async function execute(scene = active, runParams = params) {
    if (!scene) return
    setActive(scene)
    setRunning(true); setSteps([]); setResult(null); setApproval(null)
    const traceId = (crypto.randomUUID?.() || Math.random().toString(16).slice(2)).slice(0, 8)
    setTrace(traceId)
    try {
      const resp = await fetch('/api/run-workflow', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow: scene.workflow, params: runParams, trace_id: traceId }),
      })
      const body = await resp.json()
      setResult(body)
    } catch (e) {
      setResult({ isError: true, content: [{ text: String(e.message) }] })
    } finally {
      setRunning(false)
    }
  }

  async function decide(decision, overrideArgs) {
    if (!approval) return
    await fetch('/api/hitl/decide', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        approval_id: approval.approval_id,
        decision: decision === 'approve' ? 'approved' : decision === 'reject' ? 'rejected' : 'modify',
        override_args: overrideArgs,
        decided_by: 'scenes',
      }),
    })
  }

  function tryIt() {
    const scene = scenes.find((s) => s.id === 'greenhouse-irrigate') || scenes[0]
    if (scene) execute(scene, { ...(scene.params || {}), duration: 60 })
  }

  return (
    <section>
      <div className="hero">
        <h2>AI 想动手之前，先问你一句</h2>
        <p>{HERO_QUESTION}</p>
        <button onClick={tryIt} disabled={running || !scenes.length}>
          {running ? '演示进行中…' : '试试看'}
        </button>
        <span className="muted small">会依次经过：Agent 计划 → HITL 审批 → 工具执行 → 硬件响应</span>
      </div>

      <div className="bar">
        <span className="muted">预置场景模板（写操作由 Hub 的 HITL 审批闸门拦截，不需要前端二次确认）</span>
        <button className="ghost" onClick={() => getJSON('/api/scenes').then((d) => setScenes(d.items))}>刷新</button>
      </div>
      {scenes.length === 0 && <p className="muted">Hub 未启动或无场景定义（core/workflow/scenes.yaml）</p>}
      <div className="cards-wide">
        {scenes.map((s) => (
          <div key={s.id} className={'scene' + (active?.id === s.id ? ' sel' : '')}
            onClick={() => open(s)}>
            <div className="icon">{s.icon || '▶'}</div>
            <div>
              <b>{s.title}</b>
              <p className="muted">{s.description}</p>
              <span className={s.write ? 'bad' : 'ok'}>
                {s.write ? '✏️ 写操作（触发审批）' : '👀 只读'}
              </span>
            </div>
          </div>
        ))}
      </div>

      {active && (
        <div className="panel">
          <h3>{active.icon} {active.title} — 参数与执行
            {trace && <span className="mono muted small"> · trace {trace}</span>}
          </h3>
          <div className="bar">
            {Object.keys(params).map((k) => (
              <label key={k}>{k}
                <input value={params[k]}
                  onChange={(e) => setParams({ ...params, [k]: e.target.value })} />
              </label>
            ))}
            {Object.keys(params).length === 0 && <span className="muted">无参数</span>}
            <button disabled={running} onClick={() => execute()}>
              {running ? '执行中（可能等待审批）…' : '执行场景'}
            </button>
          </div>

          {approval && <ApprovalCard approval={approval} onDecide={decide} />}

          {steps.length > 0 && (
            <div className="steps">
              {steps.map((e, i) => (
                <span key={i} className={'chip ' + (e.status === 'ok' ? 'ok' : e.status)}>
                  {e.id}·{e.tool} {e.status === 'ok' ? `✓ ${e.latency_ms ?? ''}ms` : e.status}
                </span>
              ))}
            </div>
          )}

          {result && (
            <pre className={result.isError ? 'errbox' : 'okbox'}>
              {(result.content || [{}])[0]?.text?.slice(0, 700)}
            </pre>
          )}
        </div>
      )}
    </section>
  )
}
