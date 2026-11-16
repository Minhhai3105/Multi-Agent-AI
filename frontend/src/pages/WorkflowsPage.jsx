import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, auth } from '../api'
import { Alert, Badge, Card, Modal, ROLE_LABEL, STEP_LABEL, useAsync } from '../components/ui'

const LEAVE_EXAMPLE = {
  nhan_vien: 'Nguyễn Nhân Viên', loai_nghi: 'Phép năm', tu_ngay: '2026-12-01', den_ngay: '2026-12-03',
  ly_do: 'Về quê có việc gia đình', ngay_gui_don: new Date().toISOString().slice(0, 10),
}

function RunDialog({ workflow, onClose }) {
  const isLeave = workflow.name.toLowerCase().includes('nghỉ phép')
  const [fields, setFields] = useState(isLeave ? LEAVE_EXAMPLE : { request: '' })
  const [newKey, setNewKey] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [ack, setAck] = useState(null)
  const navigate = useNavigate()

  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      const t0 = performance.now()
      const res = await api.post(`/api/workflows/${workflow.id}/run`, { input: fields })
      setAck({ ...res, ms: Math.round(performance.now() - t0) })
      setTimeout(() => navigate(`/runs/${res.run_id}`), 900)
    } catch (e) { setError(e) } finally { setBusy(false) }
  }

  return (
    <Modal title={`Chạy workflow: ${workflow.name}`} onClose={onClose}>
      <p className="small muted">Dữ liệu đầu vào được chuyển cho bước 1; kết quả mỗi bước là ngữ cảnh cho bước sau.</p>
      <Alert error={error} />
      {Object.entries(fields).map(([k, v]) => (
        <label key={k} className="kv">
          <span>{k}</span>
          <textarea rows={k === 'request' || k === 'ly_do' ? 3 : 1} value={v} onChange={(e) => setFields({ ...fields, [k]: e.target.value })} />
          <button className="link" onClick={() => { const c = { ...fields }; delete c[k]; setFields(c) }}>xoá</button>
        </label>
      ))}
      <div className="row">
        <input placeholder="Thêm trường (vd: deadline)" value={newKey} onChange={(e) => setNewKey(e.target.value)} />
        <button onClick={() => { if (newKey.trim()) { setFields({ ...fields, [newKey.trim()]: '' }); setNewKey('') } }}>+ Thêm</button>
      </div>
      {ack && <div className="alert alert-ok">HTTP 202 Accepted · run_id = {ack.run_id} · phản hồi sau {ack.ms} ms (QA-3: ≤ 3 s). Đang mở trang theo dõi…</div>}
      <div className="modal-foot">
        <button onClick={onClose}>Huỷ</button>
        <button className="primary" disabled={busy || Object.values(fields).every((v) => !String(v).trim())} onClick={start}>▶ Chạy</button>
      </div>
    </Modal>
  )
}

const EMPTY_STEP = { step_type: 'agent', name: '', agent_id: '', assignee_role: 'manager', config_json: {} }

function WorkflowEditor({ workflow, agents, onClose, onSaved }) {
  const [form, setForm] = useState(() => workflow
    ? { name: workflow.name, description: workflow.description, status: workflow.status, is_chat: workflow.is_chat,
        steps: workflow.steps.map((s) => ({ ...s, agent_id: s.agent_id || '', assignee_role: s.assignee_role || 'manager' })) }
    : { name: '', description: '', status: 'active', is_chat: false, steps: [{ ...EMPTY_STEP }] })
  const [error, setError] = useState(null)

  const setStep = (i, patch) => setForm({ ...form, steps: form.steps.map((s, j) => (i === j ? { ...s, ...patch } : s)) })
  const move = (i, d) => {
    const steps = [...form.steps]
    const [s] = steps.splice(i, 1)
    steps.splice(i + d, 0, s)
    setForm({ ...form, steps })
  }
  const save = async () => {
    setError(null)
    const body = {
      ...form,
      steps: form.steps.map((s, i) => ({
        step_order: i + 1, step_type: s.step_type, name: s.name,
        agent_id: s.step_type === 'agent' ? Number(s.agent_id) || null : null,
        assignee_role: s.step_type === 'agent' ? null : s.assignee_role,
        config_json: s.config_json || {},
      })),
    }
    try {
      if (workflow) await api.put(`/api/workflows/${workflow.id}`, body)
      else await api.post('/api/workflows', body)
      onSaved()
    } catch (e) { setError(e) }
  }

  return (
    <Modal title={workflow ? `Sửa workflow #${workflow.id}` : 'Tạo workflow'} onClose={onClose} wide>
      <Alert error={error} />
      <div className="grid-2">
        <label>Tên<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>Trạng thái
          <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
            <option value="active">Hoạt động</option><option value="draft">Nháp</option><option value="inactive">Ngưng</option>
          </select>
        </label>
      </div>
      <label>Mô tả<textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
      <label className="check"><input type="checkbox" checked={form.is_chat} onChange={(e) => setForm({ ...form, is_chat: e.target.checked })} /> Hiển thị trên màn hình Chat</label>
      <h4>Các bước (chạy tuần tự theo thứ tự)</h4>
      {form.steps.map((s, i) => (
        <div className="step-edit" key={i}>
          <span className="step-no">{i + 1}</span>
          <select value={s.step_type} onChange={(e) => setStep(i, { step_type: e.target.value })}>
            <option value="agent">AI Agent</option><option value="approval">Phê duyệt</option><option value="user">Người dùng xử lý</option>
          </select>
          <input placeholder="Tên bước" value={s.name} onChange={(e) => setStep(i, { name: e.target.value })} />
          {s.step_type === 'agent' ? (
            <select value={s.agent_id} onChange={(e) => setStep(i, { agent_id: e.target.value })}>
              <option value="">— chọn Agent —</option>
              {agents.filter((a) => a.is_active).map((a) => <option key={a.id} value={a.id}>{a.name}{a.knowledge_collection ? ' 📚' : ''}</option>)}
            </select>
          ) : (
            <select value={s.assignee_role} onChange={(e) => setStep(i, { assignee_role: e.target.value })}>
              {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>Giao cho: {v}</option>)}
            </select>
          )}
          <button disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
          <button disabled={i === form.steps.length - 1} onClick={() => move(i, 1)}>↓</button>
          <button className="danger" onClick={() => setForm({ ...form, steps: form.steps.filter((_, j) => j !== i) })}>✕</button>
        </div>
      ))}
      <button onClick={() => setForm({ ...form, steps: [...form.steps, { ...EMPTY_STEP }] })}>+ Thêm bước</button>
      <div className="modal-foot">
        <button onClick={onClose}>Huỷ</button>
        <button className="primary" onClick={save}>Lưu</button>
      </div>
    </Modal>
  )
}

export default function WorkflowsPage() {
  const { data, error, reload } = useAsync(() => api.get('/api/workflows'), [])
  const canManage = ['admin', 'manager'].includes(auth.user.role)
  const agents = useAsync(() => (canManage ? api.get('/api/agents') : Promise.resolve([])), [canManage])
  const [running, setRunning] = useState(null)
  const [editing, setEditing] = useState(undefined)

  return (
    <div className="stack">
      <div className="page-head">
        <h2>Workflow</h2>
        {canManage && <button className="primary" onClick={() => setEditing(null)}>+ Tạo workflow</button>}
      </div>
      <Alert error={error} />
      <div className="wf-grid">
        {(data || []).map((w) => (
          <Card key={w.id} title={<>{w.name} {w.is_chat && <span className="tag">Chat</span>}</>} actions={<Badge status={w.status} />}>
            <p className="small muted">{w.description}</p>
            <ol className="flow">
              {w.steps.map((s) => (
                <li key={s.id} className={`flow-${s.step_type}`}>
                  <b>{s.name}</b>
                  <span className="tiny">{STEP_LABEL[s.step_type]}{s.agent_name ? ` · ${s.agent_name}` : ''}{s.assignee_role ? ` · ${ROLE_LABEL[s.assignee_role]}` : ''}</span>
                </li>
              ))}
            </ol>
            <div className="row">
              <button className="primary" disabled={w.status !== 'active'} onClick={() => setRunning(w)}>▶ Chạy</button>
              {canManage && <button onClick={() => setEditing(w)}>Sửa</button>}
            </div>
          </Card>
        ))}
      </div>
      {running && <RunDialog workflow={running} onClose={() => setRunning(null)} />}
      {editing !== undefined && (
        <WorkflowEditor workflow={editing} agents={agents.data || []} onClose={() => setEditing(undefined)}
          onSaved={() => { setEditing(undefined); reload() }} />
      )}
    </div>
  )
}
