import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { api, auth } from './api'
import { ResponseTimeChip, ROLE_LABEL, fmtDate } from './components/ui'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import ChatPage from './pages/ChatPage'
import WorkflowsPage from './pages/WorkflowsPage'
import RunDetailPage from './pages/RunDetailPage'
import HistoryPage from './pages/HistoryPage'
import TasksPage from './pages/TasksPage'
import AgentsPage from './pages/AgentsPage'
import KnowledgePage from './pages/KnowledgePage'
import { UsersPage, ActivityLogsPage, ProfilePage } from './pages/AdminPages'
import DemoPage from './pages/DemoPage'
import './styles.css'

const NAV = [
  { to: '/', label: 'Tổng quan', icon: '📊', roles: ['admin', 'manager', 'employee'] },
  { to: '/chat', label: 'Chat hỏi đáp', icon: '💬', roles: ['admin', 'manager', 'employee'] },
  { to: '/workflows', label: 'Workflow', icon: '🔀', roles: ['admin', 'manager', 'employee'] },
  { to: '/tasks', label: 'Công việc', icon: '✅', roles: ['admin', 'manager', 'employee'] },
  { to: '/history', label: 'Lịch sử chạy', icon: '🕘', roles: ['admin', 'manager', 'employee'] },
  { to: '/agents', label: 'AI Agent', icon: '🤖', roles: ['admin', 'manager'] },
  { to: '/knowledge', label: 'Kho tri thức', icon: '📚', roles: ['admin', 'manager'] },
  { to: '/users', label: 'Người dùng', icon: '👥', roles: ['admin'] },
  { to: '/activity-logs', label: 'Nhật ký hoạt động', icon: '🧾', roles: ['admin'] },
  { to: '/demo', label: 'Demo QA', icon: '🧪', roles: ['admin'] },
]

function Notifications() {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState({ items: [], unread: 0 })
  const navigate = useNavigate()
  const load = () => api.get('/api/notifications').then(setData).catch(() => {})
  useEffect(() => {
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [])
  const openItem = async (n) => {
    if (!n.is_read) await api.post(`/api/notifications/${n.id}/read`)
    setOpen(false)
    load()
    if (n.link) navigate(n.link)
  }
  return (
    <div className="notif">
      <button className="icon-btn" onClick={() => setOpen(!open)} title="Thông báo">
        🔔{data.unread > 0 && <span className="dot">{data.unread}</span>}
      </button>
      {open && (
        <div className="notif-panel">
          <div className="notif-head">
            <b>Thông báo</b>
            <button className="link" onClick={() => api.post('/api/notifications/read-all').then(load)}>Đánh dấu đã đọc</button>
          </div>
          {data.items.length === 0 && <div className="muted pad">Chưa có thông báo</div>}
          {data.items.map((n) => (
            <div key={n.id} className={`notif-item ${n.is_read ? '' : 'unread'}`} onClick={() => openItem(n)}>
              <div><b>{n.title}</b></div>
              <div className="small">{n.message}</div>
              <div className="tiny muted">{fmtDate(n.created_at)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Shell({ children }) {
  const user = auth.user
  const navigate = useNavigate()
  const logout = () => { auth.clear(); navigate('/login') }
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">🤖 Multi-Agent AI<small>Business Process Automation</small></div>
        <nav>
          {NAV.filter((n) => n.roles.includes(user.role)).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
              <span>{n.icon}</span> {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot tiny muted">C1SE.41 · Duy Tan University</div>
      </aside>
      <div className="main">
        <header className="topbar">
          <ResponseTimeChip />
          <div className="topbar-right">
            <Notifications />
            <NavLink to="/profile" className="user-chip">
              {user.full_name} <span className={`role role-${user.role}`}>{ROLE_LABEL[user.role]}</span>
            </NavLink>
            <button className="ghost" onClick={logout}>Đăng xuất</button>
          </div>
        </header>
        <div className="content">{children}</div>
      </div>
    </div>
  )
}

function Protected({ roles, children }) {
  const location = useLocation()
  if (!auth.token || !auth.user) return <Navigate to="/login" state={{ from: location }} replace />
  if (roles && !roles.includes(auth.user.role)) return <Shell><div className="alert alert-error">403 – Vai trò của bạn không có quyền truy cập trang này.</div></Shell>
  return <Shell>{children}</Shell>
}

function App() {
  const all = ['admin', 'manager', 'employee']
  const mgr = ['admin', 'manager']
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<Protected roles={all}><DashboardPage /></Protected>} />
        <Route path="/chat" element={<Protected roles={all}><ChatPage /></Protected>} />
        <Route path="/workflows" element={<Protected roles={all}><WorkflowsPage /></Protected>} />
        <Route path="/runs/:id" element={<Protected roles={all}><RunDetailPage /></Protected>} />
        <Route path="/history" element={<Protected roles={all}><HistoryPage /></Protected>} />
        <Route path="/tasks" element={<Protected roles={all}><TasksPage /></Protected>} />
        <Route path="/agents" element={<Protected roles={mgr}><AgentsPage /></Protected>} />
        <Route path="/knowledge" element={<Protected roles={mgr}><KnowledgePage /></Protected>} />
        <Route path="/users" element={<Protected roles={['admin']}><UsersPage /></Protected>} />
        <Route path="/activity-logs" element={<Protected roles={['admin']}><ActivityLogsPage /></Protected>} />
        <Route path="/demo" element={<Protected roles={['admin']}><DemoPage /></Protected>} />
        <Route path="/profile" element={<Protected roles={all}><ProfilePage /></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />)
