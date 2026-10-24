import React, { useEffect, useRef, useState } from 'react'
import { getJSON } from '../api.js'

/* 一键场景（v2.0 §3.1）：场景卡片 → 参数 → 写操作确认（渐进自主权）→ 执行 → 事件进度 */

export default function ScenesPage() {
  const [scenes, setScenes] = useState([])
  const [active, setActive] = useState(null)     // 选中的场景
  const [params, setParams] = useState({})
  const [confirming, setConfirming] = useState(false)
  const [running, setRunning] = useState(false)
  const [events, setEvents] = useState([])
  const [result, setResult] = useState(null)
  const timer = useRef(null)

  useEffect(() => {
    getJSON('/api/scenes').then((d) => setScenes(d.items)).catch(() => setScenes([]))
    return () => clearInterval(timer.current)
  }, [])

  function open(scene) {
    setActive(scene)
    setParams({ ...(scene.params || {}) })
    setConfirming(false); setRunning(false)
    setEvents([]); setResult(null)
    clearInterval(timer.current)
  }

  function parseFinal(text) {
    try { return JSON.parse(text) } catch { return null }
  }

  async function execute() {
    setConfirming(false); setRunning(true); setEvents([]); setResult(null)
    let since = 0
    try {
      const resp = await fetch('/api/run-workflow', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow: active.workflow, params }),
      })
      const body = await resp.json()
      setResult(body)
      const final = parseFinal((body.content || [{}])[0].text || '')
      const trace = final?.trace_id
      // 轮询事件直到 workflow 结束（ok/error）或超时
      timer.current = setInterval(async () => {
        try {
          const d = await getJSON(`/api/workflow-events?since=${since}`)
          since = d.items.length ? Math.max(...d.items.map((e) => e.seq)) : since
          const mine = d.items.filter((e) => !trace || e.wf === trace)
          if (mine.length) setEvents((prev) => [...prev, ...mine])
          if (mine.some((e) => e.kind === 'workflow' && e.status !== 'running')) {
            clearInterval(timer.current); setRunning(false)
          }
        } catch { /* 轮询失败继续 */ }
      }, 700)
      setTimeout(() => { clearInterval(timer.current); setRunning(false) }, 70000)
    } catch (e) {
      setResult({ isError: true, content: [{ text: String(e.message) }] })
      setRunning(false)
    }
  }

  return (
    <section>
      <div className="bar">
        <span className="muted">预置场景模板（点击执行；写操作需确认）</span>
        <button onClick={() => getJSON('/api/scenes').then((d) => setScenes(d.items))}>刷新</button>
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
                {s.write ? '✏️ 写操作（需确认）' : '👀 只读'}
              </span>
            </div>
          </div>
        ))}
      </div>

      {active && (
        <div className="panel">
          <h3>{active.icon} {active.title} — 参数与执行</h3>
          <div className="bar">
            {Object.keys(params).map((k) => (
              <label key={k}>{k}
                <input value={params[k]}
                  onChange={(e) => setParams({ ...params, [k]: e.target.value })} />
              </label>
            ))}
            {Object.keys(params).length === 0 && <span className="muted">无参数</span>}
            <button disabled={running} onClick={() => (active.write ? setConfirming(true) : execute())}>
              {running ? '执行中…' : '执行场景'}
            </button>
          </div>

          {confirming && (
            <div className="modal">
              <div className="modal-box">
                <h3>⚠️ 写操作确认</h3>
                <p>「{active.title}」将<b>控制真实设备</b>（工作流 {active.workflow}）。</p>
                <p className="muted">渐进自主权：只读场景直接执行；写场景需本次确认。</p>
                <div className="bar">
                  <button onClick={execute}>确认执行</button>
                  <button className="ghost" onClick={() => setConfirming(false)}>取消</button>
                </div>
              </div>
            </div>
          )}

          {events.length > 0 && (
            <div className="steps">
              {events.filter((e) => e.kind === 'step').map((e, i) => (
                <span key={i} className={'chip ' + (e.status === 'ok' ? 'ok' : e.status)}>
                  {e.id}·{e.tool} {e.status === 'ok' ? `✓ ${e.latency_ms ?? ''}ms` : e.status}
                </span>
              ))}
            </div>
          )}

          {result && (
            <pre className={result.isError ? 'errbox' : 'okbox'}>
              {(result.content || [{}])[0]?.text?.slice(0, 600)}
            </pre>
          )}
        </div>
      )}
    </section>
  )
}
