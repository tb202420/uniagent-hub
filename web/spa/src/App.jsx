import React, { useEffect, useMemo, useState } from 'react'
import { getJSON } from './api.js'
import ToolsPage from './pages/Tools.jsx'
import WorkflowPage from './pages/Workflow.jsx'
import SecurityPage from './pages/Security.jsx'
import AuditPage from './pages/Audit.jsx'

const TABS = [
  { key: 'tools', label: '工具注册中心' },
  { key: 'workflow', label: '工作流编排' },
  { key: 'security', label: '安全中心' },
  { key: 'audit', label: '审计日志' },
]

export default function App() {
  const [tab, setTab] = useState('tools')
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">UniAgent Hub <span>管理控制台</span></div>
        <nav>
          {TABS.map((t) => (
            <button
              key={t.key}
              className={tab === t.key ? 'tab active' : 'tab'}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <a className="gh" href="https://github.com/tb202420/uniagent-hub" target="_blank" rel="noreferrer">GitHub</a>
      </header>
      <main>
        {tab === 'tools' && <ToolsPage />}
        {tab === 'workflow' && <WorkflowPage />}
        {tab === 'security' && <SecurityPage />}
        {tab === 'audit' && <AuditPage />}
      </main>
      <footer>React 19 + React Flow 12 初版 · 数据源：Dashboard JSON API（/api/*）</footer>
    </div>
  )
}
