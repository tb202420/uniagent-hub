import React, { useState } from 'react'
import ConsolePage from './pages/Console.jsx'
import TerminalPage from './pages/Terminal.jsx'
import ScenesPage from './pages/Scenes.jsx'
import WorkflowPage from './pages/Workflow.jsx'
import ToolsPage from './pages/Tools.jsx'
import SecurityPage from './pages/Security.jsx'
import AuditPage from './pages/Audit.jsx'
import RecentRuns from './pages/RecentRuns.jsx'

const LAYERS = [
  { key: 'monitor', label: '① 监视层' },
  { key: 'control', label: '② 控制层' },
  { key: 'orchestrate', label: '③ 编排层' },
]

const EXPERT_TABS = [
  ...LAYERS,
  { key: 'workflow', label: 'DAG 工作流' },
  { key: 'tools', label: '工具注册中心' },
  { key: 'security', label: '安全中心' },
  { key: 'audit', label: '审计日志' },
]
const SIMPLE_TABS = [
  ...LAYERS,
  { key: 'recent', label: '最近执行' },
  { key: 'audit', label: '审计日志' },
]

export default function App() {
  const [mode, setMode] = useState(
    () => localStorage.getItem('ua-mode') || 'simple')
  const [tab, setTab] = useState('orchestrate')

  function switchMode(next) {
    setMode(next)
    localStorage.setItem('ua-mode', next)
    setTab(next === 'simple' ? 'orchestrate' : 'monitor')
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">UniAgent Hub <span>{mode === 'simple' ? '简易模式' : '专家模式'}</span></div>
        <nav>
          {(mode === 'simple' ? SIMPLE_TABS : EXPERT_TABS).map((t) => (
            <button key={t.key} className={tab === t.key ? 'tab active' : 'tab'}
              onClick={() => setTab(t.key)}>{t.label}</button>
          ))}
        </nav>
        <button className="mode" onClick={() => switchMode(mode === 'simple' ? 'expert' : 'simple')}>
          {mode === 'simple' ? '切换专家模式' : '切换简易模式'}
        </button>
        <a className="gh" href="https://github.com/tb202420/uniagent-hub" target="_blank" rel="noreferrer">GitHub</a>
      </header>
      <main>
        {tab === 'monitor' && <ConsolePage />}
        {tab === 'control' && <TerminalPage />}
        {tab === 'orchestrate' && <ScenesPage />}
        {tab === 'recent' && <RecentRuns />}
        {tab === 'workflow' && <WorkflowPage />}
        {tab === 'tools' && <ToolsPage />}
        {tab === 'security' && <SecurityPage />}
        {tab === 'audit' && <AuditPage />}
      </main>
      <footer>
        监视层（流式 + RAF + 瀑布图）· 控制层（xterm + HITL 审批）· 编排层（场景 + DAG）
        {' '}· OTel GenAI SemConv 数据源
      </footer>
    </div>
  )
}
