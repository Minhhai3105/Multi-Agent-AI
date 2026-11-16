import { useState } from 'react'
import { api } from '../api'
import { Alert, Badge, Card, Modal, fmtDate, useAsync } from '../components/ui'

const EMPTY = { name: '', role_name: '', instruction: '', model_name: 'default', temperature: 0.3, knowledge_collection: '', is_active: true }

function AgentForm({ agent, collections, onClose, onSaved }) {
  const [form, setForm] = useState(agent ? { ...agent, knowledge_collection: agent.knowledge_collection || '' } : EMPTY)
  const [error, setError] = useState(null)
  const save = async () => {
    const body = {
      name: form.name, role_name: form.role_name, instruction: form.instruction, model_name: form.model_name,
      temperature: Number(form.temperature), knowledge_collection: form.knowledge_collection || null, is_active: form.is_active,
    }
    try {
      if (agent) await api.put(`/api/agents/${agent.id}`, body)
      else await api.post('/api/agents', body)
      onSaved()
    } catch (e) { setError(e) }
  }
  return (
    <Modal title={agent ? `Sửa Agent #${agent.id}` : 'Tạo AI Agent'} onClose={onClose} wide>
      <p className="small muted">Agent là một cấu hình (vai trò + chỉ dẫn + model), không phải code mới (ràng buộc C2).</p>
      <Alert error={error} />
      <div className="grid-2">
        <label>Tên Agent<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>Vai trò<input value={form.role_name} onChange={(e) => setForm({ ...form, role_name: e.target.value })} /></label>
      </div>
      <label>Chỉ dẫn (system instruction)<textarea rows={5} value={form.instruction} onChange={(e) => setForm({ ...form, instruction: e.target.value })} /></label>
      <div className="grid-3">
        <label>Model (<code>default</code> = model trong .env)<input value={form.model_name} onChange={(e) => setForm({ ...form, model_name: e.target.value })} /></label>
        <label>Temperature ({form.temperature})<input type="range" min="0" max="2" step="0.1" value={form.temperature} onChange={(e) => setForm({ ...form, temperature: e.target.value })} /></label>
        <label>Kho tri thức (RAG)
          <select value={form.knowledge_collection} onChange={(e) => setForm({ ...form, knowledge_collection: e.target.value })}>
            <option value="">— không dùng —</option>
            {collections.map((c) => <option key={c.name} value={c.name}>{c.name} ({c.documents} tài liệu)</option>)}
          </select>
        </label>
      </div>
      <label className="check"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Đang hoạt động</label>
      <div className="modal-foot"><button onClick={onClose}>Huỷ</button><button className="primary" onClick={save}>Lưu</button></div>
    </Modal>
  )
}

export default function AgentsPage() {
  const { data, error, reload } = useAsync(() => api.get('/api/agents'), [])
  const collections = useAsync(() => api.get('/api/knowledge/collections'), [])
  const [editing, setEditing] = useState(undefined)
  const [msg, setMsg] = useState(null)
  const [err, setErr] = useState(null)

  const remove = async (a) => {
    if (!window.confirm(`Xoá Agent "${a.name}"? Agent đã có lịch sử sẽ được vô hiệu hoá thay vì xoá.`)) return
    try {
      const r = await api.del(`/api/agents/${a.id}`)
      setMsg(r.deleted ? 'Đã xoá Agent.' : 'Agent đã có lịch sử chạy nên được vô hiệu hoá (giữ lịch sử – D10).')
      reload()
    } catch (e) { setErr(e) }
  }

  return (
    <div className="stack">
      <div className="page-head"><h2>AI Agent</h2><button className="primary" onClick={() => setEditing(null)}>+ Tạo Agent</button></div>
      <Alert error={error || err} onClose={() => setErr(null)} />
      {msg && <Alert error={msg} kind="ok" onClose={() => setMsg(null)} />}
      <div className="wf-grid">
        {(data || []).map((a) => (
          <Card key={a.id} title={<>🤖 {a.name}</>} actions={<Badge status={a.is_active ? 'active' : 'inactive'} />}>
            <div className="small"><b>{a.role_name}</b> · {a.model_name} · t={a.temperature}</div>
            {a.knowledge_collection && <div className="tag">📚 RAG: {a.knowledge_collection}</div>}
            <p className="small muted clamp">{a.instruction}</p>
            <div className="tiny muted">
              Đã chạy {a.total_runs} bước · {a.done_runs} thành công · {a.failed_runs} thất bại
              {a.last_status && <> · gần nhất <Badge status={a.last_status} /> {fmtDate(a.last_run_at)}</>}
            </div>
            <div className="row">
              <button onClick={() => setEditing(a)}>Sửa</button>
              <button className="danger" onClick={() => remove(a)}>Xoá</button>
            </div>
          </Card>
        ))}
      </div>
      {editing !== undefined && (
        <AgentForm agent={editing} collections={collections.data || []} onClose={() => setEditing(undefined)}
          onSaved={() => { setEditing(undefined); reload() }} />
      )}
    </div>
  )
}
