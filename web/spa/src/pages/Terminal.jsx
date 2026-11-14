import React, { useCallback, useEffect, useRef, useState } from 'react'
import '@xterm/xterm/css/xterm.css'
import { getJSON, postJSON } from '../api.js'
import { useEventStream } from '../hooks/useEventStream.js'
import { useTakeover } from '../store/takeover.js'
import ApprovalCard from '../components/ApprovalCard.jsx'

/* 控制层：xterm.js 交互终端 + HITL 审批 + 人机接管状态机 */

export default function TerminalPage() {
  const hostRef = useRef(null)
  const termRef = useRef(null)
  const fitRef = useRef(null)
  const wsRef = useRef(null)
  const [status, setStatus] = useState('连接中…')
  const mode = useTakeover((s) => s.mode)          // agent | human（Zustand 状态机）
  const setMode = useTakeover((s) => s.setMode)
  const modeRef = useRef(mode)
  modeRef.current = mode
  const [sessionMode, setSessionMode] = useState('')
  const [approval, setApproval] = useState(null)
  const [wsStatus, setWsStatus] = useState('idle')

  useEffect(() => {
    getJSON('/api/hitl/pending').then((d) => {
      if ((d.items || []).length) setApproval(d.items[0])
    }).catch(() => {})
  }, [])

  useEventStream(useCallback((e) => {
    if (e.kind === '__status') { setWsStatus(e.status); return }
    if (e.kind === 'hitl.request') setApproval(e.approval)
    if (e.kind === 'hitl.decision' && approval?.approval_id === e.approval.approval_id) {
      setApproval(e.approval)
    }
    if (e.kind === 'terminal.command') {
      // 写工具实际下发的命令（注释行标注，不伪装成 shell 输入）
      const args = JSON.stringify(e.args || {})
      const tail = e.ok ? `ok ${e.latency_ms || 0}ms` : `失败 ${e.error || ''}`
      termRef.current?.write(
        `\r\n\x1b[36m[Agent→设备] ${e.tool} ${args} → ${tail}\x1b[0m\r\n`)
    }
  }, [approval]))

  useEffect(() => {
    let disposed = false
    let term = null
    let fit = null
    let termData = null
    let termResize = null

    async function connect() {
      try {
        const cfg = await postJSON('/api/terminal-config', {})
        if (cfg.error) throw new Error(cfg.error)
        if (disposed) return
        const ws = new WebSocket(cfg.url, [`${cfg.protocol_prefix}.${cfg.token}`])
        wsRef.current = ws
        ws.onopen = () => {
          setStatus('已连接')
          ws.send(JSON.stringify({ type: 'resize', rows: term.rows, cols: term.cols }))
        }
        ws.onmessage = (ev) => {
          let msg
          try { msg = JSON.parse(ev.data) } catch { return }
          if (msg.kind === 'terminal.output') term.write(msg.data || '')
          else if (msg.kind === 'terminal.state') {
            setStatus(msg.state === 'running' ? '运行中' : msg.state === 'blocked' ? '输入被拦截' : '已关闭')
            if (msg.mode) setSessionMode(msg.mode)
            if (msg.state === 'blocked' && msg.reason) {
              term.write(`\r\n\x1b[31m${msg.reason}\x1b[0m\r\n`)
            }
            if (msg.reason && msg.state !== 'blocked') term.write(`\r\n[${msg.reason}]\r\n`)
          }
        }
        ws.onclose = () => setStatus('已断开')
        ws.onerror = () => setStatus('连接失败')
      } catch (e) {
        setStatus(`连接失败：${e.message}`)
      }
    }

    async function boot() {
      // 代码分割：xterm 体积大，仅在进入控制层时加载（低配部署友好）
      const [{ Terminal }, { FitAddon }] = await Promise.all([
        import('@xterm/xterm'), import('@xterm/addon-fit')])
      if (disposed) return
      term = new Terminal({
        cursorBlink: true,
        fontSize: 13,
        fontFamily: 'ui-monospace, Consolas, monospace',
        theme: { background: '#0b1720', foreground: '#d8e7ee', cursor: '#39c2d7' },
        convertEol: false,
      })
      fit = new FitAddon()
      term.loadAddon(fit)
      term.open(hostRef.current)
      fit.fit()
      termRef.current = term
      fitRef.current = fit

      termData = term.onData((data) => {
        if (modeRef.current !== 'human') {
          term.write('\r\n\x1b[33m[Agent 控制中] 点击上方「接管终端」后才能输入\x1b[0m\r\n')
          return
        }
        const ws = wsRef.current
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'input', data }))
        }
      })
      termResize = term.onResize(({ rows, cols }) => {
        const ws = wsRef.current
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'resize', rows, cols }))
        }
      })
      connect()
    }
    boot()

    const onWinResize = () => { try { fit?.fit() } catch { /* noop */ } }
    window.addEventListener('resize', onWinResize)
    return () => {
      disposed = true
      window.removeEventListener('resize', onWinResize)
      termData?.dispose()
      termResize?.dispose()
      if (wsRef.current) wsRef.current.close()
      term?.dispose()
    }
  }, [])

  async function decide(decision, overrideArgs) {
    if (!approval) return
    await postJSON('/api/hitl/decide', {
      approval_id: approval.approval_id,
      decision: decision === 'approve' ? 'approved' : decision === 'reject' ? 'rejected' : 'modify',
      override_args: overrideArgs,
      decided_by: 'terminal-console',
    })
  }

  function switchMode(next) {
    setMode(next)
    if (next === 'human') termRef.current?.focus()
    else {
      termRef.current?.write('\r\n\x1b[36m[已交还 Agent 控制]\x1b[0m\r\n')
    }
  }

  return (
    <section>
      <div className="bar">
        <span className={'ws ' + wsStatus}>{wsStatus === 'open' ? '事件流已连接' : wsStatus}</span>
        <span className="muted">
          终端控制台 · {sessionMode === 'pty' ? 'POSIX 伪终端（pty）'
            : sessionMode === 'pipe' ? 'Windows 管道会话（非 PTY，如实标注）' : '连接中'}
          · {status}
        </span>
        <span className={'takeover ' + mode}>{mode === 'human' ? '人工控制' : 'Agent 控制'}</span>
        <button className="ghost" onClick={() => switchMode(mode === 'human' ? 'agent' : 'human')}>
          {mode === 'human' ? '交还 Agent' : '接管终端'}
        </button>
      </div>

      {approval && <ApprovalCard approval={approval} onDecide={decide} />}

      <div className="panel terminal-panel">
        {mode === 'agent' && (
          <div className="term-overlay">Agent 控制中 · 点击右上方「接管终端」后可直接输入</div>
        )}
        <div ref={hostRef} className="xterm-host" />
      </div>

      <p className="muted small">
        Guard 纪律：sudo / 提权 / curl / ssh / 网络地址等输入会被拦截并写入审计；
        token 单次有效、60s TTL、经 Sec-WebSocket-Protocol 传递。
      </p>
    </section>
  )
}
