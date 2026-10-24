import React, { useEffect, useState } from 'react'
import { getJSON } from '../api.js'

export default function ToolsPage() {
  const [items, setItems] = useState(null)
  const [q, setQ] = useState('')
  const [err, setErr] = useState('')

  async function load() {
    try { setItems((await getJSON('/api/tools')).items); setErr('') }
    catch (e) { setErr(String(e.message)) }
  }
  useEffect(() => { load() }, [])

  const filtered = (items || []).filter((t) =>
    !q || t.name.includes(q) || (t.description || '').includes(q))

  return (
    <section>
      <div className="bar">
        <input placeholder="按名称/描述筛选…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted">{items ? `${filtered.length}/${items.length} 个工具（Hub 未启动时为空）` : '加载中…'}</span>
        <button onClick={load}>刷新</button>
      </div>
      {err && <div className="err">Hub 不可达：{err}（先启动 Hub，刷新重试）</div>}
      <table>
        <thead><tr><th>工具名</th><th>说明</th><th>只读</th></tr></thead>
        <tbody>
          {filtered.map((t) => (
            <tr key={t.name}>
              <td className="mono">{t.name}</td>
              <td>{t.description}</td>
              <td>{t.readOnly ? '✅ read' : '✏️ write'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
