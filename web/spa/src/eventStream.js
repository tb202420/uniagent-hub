// 单连接事件流（v3.0 三层控制台共享数据源）
// 浏览器 WebSocket 子协议携带单次 token（不在 URL 暴露）；断线自动重连并重新领 token。
import { getJSON, postJSON } from './api.js'

class EventStream {
  constructor() {
    this.subs = new Set()
    this.ws = null
    this.status = 'idle'
    this.seq = 0
    this.closed = false
    this.retry = 0
  }

  subscribe(fn) {
    this.subs.add(fn)
    if (this.status === 'idle') this.connect()
    return () => this.subs.delete(fn)
  }

  emit(event) {
    if (event && event.seq) this.seq = Math.max(this.seq, event.seq)
    this.subs.forEach((fn) => {
      try { fn(event) } catch { /* 单个视图异常不影响其它视图 */ }
    })
  }

  async connect() {
    if (this.closed) return
    this.setStatus('connecting')
    try {
      const cfg = await postJSON('/api/ws-config', {})
      if (cfg.error) throw new Error(cfg.error)
      const proto = `${cfg.protocol_prefix}.${cfg.token}`
      const ws = new WebSocket(cfg.url, [proto])
      this.ws = ws
      ws.onopen = () => { this.retry = 0; this.setStatus('open') }
      ws.onmessage = (e) => {
        try { this.emit(JSON.parse(e.data)) } catch { /* 忽略坏帧 */ }
      }
      ws.onclose = () => {
        this.setStatus('closed')
        this.scheduleReconnect()
      }
      ws.onerror = () => { try { ws.close() } catch { /* noop */ } }
    } catch {
      this.setStatus('error')
      this.scheduleReconnect()
    }
  }

  scheduleReconnect() {
    if (this.closed) return
    this.retry += 1
    const delay = Math.min(5000, 300 * this.retry)
    setTimeout(() => this.connect(), delay)
  }

  setStatus(status) {
    this.status = status
    this.subs.forEach((fn) => {
      try { fn({ kind: '__status', status }) } catch { /* noop */ }
    })
  }

  close() {
    this.closed = true
    if (this.ws) this.ws.close()
  }
}

let shared = null

export function getEventStream() {
  if (!shared) shared = new EventStream()
  return shared
}

// 轮询兜底：WS 不可用时按 seq 增量拉取（演示环境被代理阻断时的降级路径）
export async function pollEvents(sinceRef) {
  const data = await getJSON(`/api/events?since=${sinceRef.current}`)
  const items = data.items || []
  if (items.length) sinceRef.current = Math.max(...items.map((e) => e.seq))
  return items
}
