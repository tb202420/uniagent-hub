import React, { useEffect, useState } from 'react'
import { getJSON } from '../api.js'

export default function RecentRuns() {
  const [runs, setRuns] = useState(null)
  async function load() {
    try { setRuns((await getJSON('/api/workflows')).items.slice(0, 15)) }
    catch { setRuns([]) }
  }
  useEffect(() => { load() }, [])
  return (
    <section>
      <div className="bar">
        <span className="muted">最近工作流执行（简易模式视图）</span>
        <button onClick={load}>刷新</button>
      </div>
      <table>
        <thead><tr><th>工作流</th><th>结果</th><th>trace</th><th>步骤</th></tr></thead>
        <tbody>
          {(runs || []).map((r, i) => (
            <tr key={i}>
              <td className="mono">{r.workflow}</td>
              <td className={r.ok ? 'ok' : 'bad'}>{r.ok ? 'ok' : 'failed'}</td>
              <td className="mono">{r.trace_id}</td>
              <td>{(r.steps || []).map((s) => `${s.id}:${s.status}`).join(' · ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {runs && runs.length === 0 && <p className="muted">暂无执行记录</p>}
    </section>
  )
}
