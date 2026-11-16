import { useState } from 'react'
import { api, auth, qs } from '../api'
import { Alert, Badge, Card, Json, Modal, Pager, ROLE_LABEL, fmtDate, useAsync } from '../components/ui'

export function UsersPage() {
  const { data, error, reload } = useAsync(() => api.get('/api/users?page_size=50'), [])
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ email: '', full_name: '', role: 'employee', password: '' })
  const [err, setErr] = useState(null)

  const update = async (u, patch) => {
    setErr(null)
    try { await api.put(`/api/users/${u.id}`, patch); reload() } catch (e) { setErr(e) }
  }
  const create = async () => {
    try { await api.post('/api/users', form); setCreating(false); setForm({ email: '', full_name: '', role: 'employee', password: '' }); reload() } catch (e) { setErr(e) }
  }

  return (
    <div className="stack">
      <div className="page-head"><h2>Người dùng & vai trò</h2><button className="primary" onClick={() => setCreating(true)}>+ Thêm người dùng</button></div>
      <Alert error={error || err} onClose={() => setErr(null)} />
      <Card>
        <table>
          <thead><tr><th>#</th><th>Họ tên</th><th>Email</th><th>Vai trò</th><th>Trạng thái</th><th>Tạo lúc</th></tr></thead>
          <tbody>
            {(data?.items || []).map((u) => (
              <tr key={u.id}>
                <td>{u.id}</td><td>{u.full_name}</td><td>{u.email}</td>
                <td>
                  <select value={u.role} disabled={u.id === auth.user.id} onChange={(e) => update(u, { role: e.target.value })}>
                    {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </td>
                <td>
                  <button className="small" disabled={u.id === auth.user.id} onClick={() => update(u, { is_active: !u.is_active })}>
                    {u.is_active ? '✓ Hoạt động' : '✕ Vô hiệu'}
                  </button>
                </td>
                <td className="small">{fmtDate(u.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {creating && (
        <Modal title="Thêm người dùng" onClose={() => setCreating(false)}>
          <label>Email<input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label>Họ tên<input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label>
          <label>Vai trò<select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label>Mật khẩu (≥ 8 ký tự)<input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
          <div className="modal-foot"><button onClick={() => setCreating(false)}>Huỷ</button><button className="primary" onClick={create}>Tạo</button></div>
        </Modal>
      )}
    </div>
  )
}

export function ActivityLogsPage() {
  const [filters, setFilters] = useState({ entity_type: '', action: '' })
  const [page, setPage] = useState(1)
  const { data, error } = useAsync(() => api.get(`/api/activity-logs${qs({ ...filters, page, page_size: 30 })}`), [JSON.stringify(filters), page])
  const [detail, setDetail] = useState(null)
  return (
    <div className="stack">
      <div className="page-head"><h2>Nhật ký hoạt động (QA-6)</h2></div>
      <p className="small muted">Mỗi thao tác quản trị, khởi chạy, retry, phê duyệt đều sinh một bản ghi (ai · làm gì · đối tượng · lúc nào), ghi trong cùng giao dịch với thay đổi nghiệp vụ.</p>
      <Card>
        <div className="filters">
          <select value={filters.entity_type} onChange={(e) => { setFilters({ ...filters, entity_type: e.target.value }); setPage(1) }}>
            <option value="">Mọi đối tượng</option>
            {['user', 'agent', 'workflow', 'workflow_run', 'step_run', 'task', 'knowledge_document', 'system'].map((t) => <option key={t}>{t}</option>)}
          </select>
          <input placeholder="action (vd: step_run.manual_retry)" value={filters.action} onChange={(e) => { setFilters({ ...filters, action: e.target.value }); setPage(1) }} />
        </div>
      </Card>
      <Alert error={error} />
      <Card>
        <table>
          <thead><tr><th>Thời gian</th><th>Người thực hiện</th><th>Hành động</th><th>Đối tượng</th><th>Nội dung</th><th /></tr></thead>
          <tbody>
            {(data?.items || []).map((l) => (
              <tr key={l.id}>
                <td className="small">{fmtDate(l.created_at)}</td>
                <td>{l.user_name}</td>
                <td><code>{l.action}</code></td>
                <td className="small">{l.entity_type}{l.entity_id ? ` #${l.entity_id}` : ''}</td>
                <td className="small">{l.message}</td>
                <td>{Object.keys(l.detail || {}).length > 0 && <button className="small" onClick={() => setDetail(l)}>Chi tiết</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && <Pager page={page} pageSize={30} total={data.total} onPage={setPage} />}
      </Card>
      {detail && <Modal title={`${detail.action} · ${detail.entity_type} #${detail.entity_id ?? ''}`} onClose={() => setDetail(null)}><Json value={detail.detail} /></Modal>}
    </div>
  )
}

export function ProfilePage() {
  const { data, reload } = useAsync(() => api.get('/api/me'), [])
  const [form, setForm] = useState({ full_name: '', current_password: '', new_password: '' })
  const [msg, setMsg] = useState(null)
  const [err, setErr] = useState(null)
  const save = async () => {
    setErr(null)
    try {
      const body = { full_name: form.full_name || undefined }
      if (form.new_password) Object.assign(body, { current_password: form.current_password, new_password: form.new_password })
      const u = await api.put('/api/me', body)
      auth.save(auth.token, u)
      setMsg('Đã cập nhật hồ sơ.')
      setForm({ full_name: '', current_password: '', new_password: '' })
      reload()
    } catch (e) { setErr(e) }
  }
  if (!data) return null
  return (
    <div className="stack narrow">
      <div className="page-head"><h2>Hồ sơ cá nhân</h2><Badge status="active">{ROLE_LABEL[data.role]}</Badge></div>
      <Alert error={err} onClose={() => setErr(null)} />
      {msg && <Alert error={msg} kind="ok" onClose={() => setMsg(null)} />}
      <Card>
        <p><b>{data.full_name}</b> · {data.email}</p>
        <label>Họ tên mới<input value={form.full_name} placeholder={data.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label>
        <div className="grid-2">
          <label>Mật khẩu hiện tại<input type="password" value={form.current_password} onChange={(e) => setForm({ ...form, current_password: e.target.value })} /></label>
          <label>Mật khẩu mới (≥ 8 ký tự)<input type="password" value={form.new_password} onChange={(e) => setForm({ ...form, new_password: e.target.value })} /></label>
        </div>
        <button className="primary" onClick={save}>Lưu</button>
      </Card>
    </div>
  )
}
