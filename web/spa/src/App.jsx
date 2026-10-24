import React, { useEffect, useState } from 'react'
import { getJSON } from './api.js'
import ToolsPage from './pages/Tools.jsx'
import WorkflowPage from './pages/Workflow.jsx'
import SecurityPage from './pages/Security.jsx'
import AuditPage from './pages/Audit.jsx'
import ScenesPage from './pages/Scenes.jsx'
import RecentRuns from './pages/RecentRuns.jsx'

const EXPERT_TABS = [
  { key: 'tools', label: '工具注册中心' },
  { key: 'workflow', label: '工作流编排' },
  { key: 'security', label: '安全中心' },
  { key: 'audit', label: '审计日志' },
]
const SIMPLE_TABS = [
  { key: 'scenes', label: '一键场景' },
  { key: 'recent', label: '最近执行' },
  { key: 'audit', label: '审计日志' },
]

export default function App() {
  const [mode, setMode] = useState(
    () => localStorage.getItem('ua-mode') || 'simple')
  const [tab, setTab] = useState(mode === 'simple' ? 'scenes' : 'tools')

  function switchMode(next) {
    setMode(next)
    localStorage.setItem('ua-mode', next)
    setTab(next === 'simple' ? 'scenes' : 'tools')
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
        {tab === 'scenes' && <ScenesPage />}
        {tab === 'recent' && <RecentRuns />}
        {tab === 'tools' && <ToolsPage />}
        {tab === 'workflow' && <WorkflowPage />}
        {tab === 'security' && <SecurityPage />}
        {tab === 'audit' && <AuditPage />}
      </main>
      <footer>React 19 + React Flow 12（ELK 布局）· {mode === 'simple'
        ? '场景模板 + 写操作确认（渐进自主权）'
        : '工具 / DAG / 安全 / 审计'}</footer>
    </div>
  )
}
