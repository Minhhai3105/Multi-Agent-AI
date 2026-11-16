import { useEffect, useRef, useState, useCallback } from 'react'
import { metrics } from '../api'

export const STATUS_LABEL = {
  running: 'Đang chạy', completed: 'Hoàn thành', failed: 'Thất bại', cancelled: 'Đã huỷ',
  pending: 'Chờ', in_progress: 'Đang xử lý', done: 'Xong',
  todo: 'Cần làm', draft: 'Nháp', active: 'Hoạt động', inactive: 'Ngưng',
}
export const ROLE_LABEL = { admin: 'Admin', manager: 'Manager', employee: 'Employee' }
export const STEP_LABEL = { agent: 'AI Agent', user: 'Người dùng', approval: 'Phê duyệt' }

export function Badge({ status, children }) {
  return <span className={`badge badge-${status}`}>{children || STATUS_LABEL[status] || status}</span>
}

export function fmtDate(value) {
  if (!value) return '—'
  const d = new Date(value)
  return d.toLocaleString('vi-VN', { hour12: false, day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function duration(a, b) {
  if (!a || !b) return ''
  const ms = new Date(b) - new Date(a)
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

export function Card({ title, actions, children, className = '' }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          <h3>{title}</h3>
          <div className="card-actions">{actions}</div>
        </div>
      )}
      {children}
    </section>
  )
}

export function Alert({ error, kind = 'error', onClose }) {
  if (!error) return null
  const text = typeof error === 'string' ? error : error.message
  return (
    <div className={`alert alert-${kind}`}>
      <span>{error.status ? <b>HTTP {error.status}: </b> : null}{text}</span>
      {onClose && <button className="link" onClick={onClose}>✕</button>}
    </div>
  )
}

export function Modal({ title, onClose, children, wide }) {
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className={`modal ${wide ? 'modal-wide' : ''}`} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="link" onClick={onClose}>✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Json({ value }) {
  if (value === null || value === undefined) return <span className="muted">—</span>
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>
}

export function Pager({ page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div className="pager">
      <span className="muted">{total.toLocaleString('vi-VN')} bản ghi · trang {page}/{pages}</span>
      <button disabled={page <= 1} onClick={() => onPage(page - 1)}>‹ Trước</button>
      <button disabled={page >= pages} onClick={() => onPage(page + 1)}>Sau ›</button>
    </div>
  )
}

// Polls `load` every `interval` ms while `active` is true (status polling, decision D05).
export function usePolling(load, interval, active) {
  const saved = useRef(load)
  saved.current = load
  useEffect(() => {
    if (!active) return undefined
    const id = setInterval(() => saved.current(), interval)
    return () => clearInterval(id)
  }, [interval, active])
}

export function useAsync(fn, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const run = useCallback(async () => {
    try {
      const data = await fn()
      setState({ data, error: null, loading: false })
      return data
    } catch (error) {
      setState((s) => ({ ...s, error, loading: false }))
      return null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { run() }, [run])
  return { ...state, reload: run, setData: (data) => setState((s) => ({ ...s, data })) }
}

export function ResponseTimeChip() {
  const [m, setM] = useState(metrics.last)
  useEffect(() => {
    metrics.listeners.add(setM)
    return () => metrics.listeners.delete(setM)
  }, [])
  if (!m || Number.isNaN(m.serverMs)) return null
  const slow = m.serverMs > 2000
  return (
    <span className={`rt-chip ${slow ? 'rt-slow' : ''}`} title={`${m.method} ${m.path} → HTTP ${m.status}`}>
      ⏱ {m.method} {m.path.split('?')[0]} · server {m.serverMs.toFixed(0)} ms
    </span>
  )
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>
}
