import React, { useEffect, useState } from 'react'
import { getJSON } from '../api.js'

export default function AuditPage() {
  const [rows, setRows] = useState([])
  const [tool, setTool] = useState('')
  const [caller, setCaller] = useState('')
  const [code, setCode] = useState('')

  async function load() {
    const params = new URLSearchParams()
    if (tool) params.set('tool', tool)
    if (caller) params.set('caller', caller)
    if (code) params.set('error_code', code)
    try { setRows((await getJSON(`/api/audit?${params}`)).items) } catch { setRows([]) }
  }
  useEffect(() => { load() }, [])

  return (
    <section>
      <div className="bar">
        <input placeholder="工具名" value={tool} onChange={(e) => setTool(e.target.value)} />
        <input placeholder="caller" value={caller} onChange={(e) => setCaller(e.target.value)} />
        <input placeholder="错误码" className="w80" value={code} onChange={(e) => setCode(e.target.value)} />
        <button onClick={load}>筛选</button>
      </div>
      <table>
        <thead><tr><th>trace_id</th><th>工具</th><th>caller</th><th>结果</th><th>错误码</th><th>延迟</th><th>schema_hash</th><th>时间</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="mono">{r.trace_id}</td>
              <td className="mono">{r.tool_name}</td>
              <td>{r.caller}</td>
              <td className={r.is_error === 0 ? 'ok' : 'bad'}>{r.is_error === 0 ? 'passed' : 'blocked'}</td>
              <td className="mono">{r.error_code || '-'}</td>
              <td>{Math.round(r.latency_ms || 0)}ms</td>
              <td className="mono" title={r.schema_hash}>{(r.schema_hash || '').slice(0, 10) || '-'}</td>
              <td>{(r.ts || '').replace('T', ' ').slice(0, 19)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
