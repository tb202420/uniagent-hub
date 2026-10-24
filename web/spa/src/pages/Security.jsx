import React, { useEffect, useState } from 'react'
import { getJSON } from '../api.js'

const ERROR_LABELS = {
  1001: '工具不存在', 1002: '参数校验失败', 1003: '权限不足（越权）',
  1004: '限流触发', 1005: '执行超时', 1006: '资源不可用',
  1007: '注入拦截', 1999: '内部错误',
}

export default function SecurityPage() {
  const [stats, setStats] = useState(null)
  const [err, setErr] = useState('')

  async function load() {
    try { setStats(await getJSON('/api/stats')); setErr('') }
    catch (e) { setErr(String(e.message)) }
  }
  useEffect(() => { load() }, [])

  const rate = stats && stats.total ? ((stats.ok / stats.total) * 100).toFixed(1) : '0.0'
  const maxCount = Math.max(1, ...((stats?.blocked_by_error || []).map((b) => b.count)))

  return (
    <section>
      <div className="bar">
        <span className="muted">Guard 管道拦截统计（SQLite 聚合）</span>
        <button onClick={load}>刷新</button>
      </div>
      {err && <div className="err">不可达：{err}</div>}
      <div className="cards">
        <div className="card"><b>{stats ? stats.total : '—'}</b><span>调用总数</span></div>
        <div className="card"><b>{rate}%</b><span>成功率</span></div>
        <div className="card"><b>{stats ? Math.round(stats.avg_latency) : '—'}ms</b><span>平均延迟</span></div>
        <div className="card"><b>{stats ? stats.total - stats.ok : '—'}</b><span>被拦截/失败</span></div>
      </div>
      <h3>按错误码分布</h3>
      {(stats?.blocked_by_error || []).length === 0 && <p className="muted">暂无拦截记录（调用一些工具或跑一轮安全测试后刷新）</p>}
      {(stats?.blocked_by_error || []).map((b) => (
        <div className="hbar" key={b.error_code}>
          <span className="mono w110">{b.error_code} {ERROR_LABELS[b.error_code] || ''}</span>
          <div className="track"><div className="fill" style={{ width: `${(b.count / maxCount) * 100}%` }} /></div>
          <span className="w40">{b.count}</span>
        </div>
      ))}
    </section>
  )
}
