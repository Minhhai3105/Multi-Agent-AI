import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, auth, qs } from '../api'
import { Alert, Badge, Card, Modal, Pager, fmtDate, useAsync, usePolling } from '../components/ui'

function DecideDialog({ task, onClose, onDone }) {
  const [comment, setComment] = useState('')
  const [text, setText] = useState('')
  const [error, setError] = useState(null)
  const isApproval = task.task_type === 'approval'
  const submit = async (decision) => {
    setError(null)
    try {
      const result = isApproval ? { decision, comment } : { text, comment }
      await api.put(`/api/tasks/${task.id}`, { status: decision === 'rejected' && !isApproval ? 'failed' : 'done', result })
      onDone()
    } catch (e) { setError(e) }
  }
  return (
    <Modal title={`${isApproval ? 'Phê duyệt' : 'Hoàn thành'} task #${task.id}`} onClose={onClose} wide>
      <Alert error={error} />
      <h4>{task.title}</h4>
      <pre className="task-desc">{task.description}</pre>
      {!isApproval && <label>Kết quả xử lý (chuyển cho bước sau)<textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} /></label>}
      <label>Ghi chú<textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder={isApproval ? 'Lý do duyệt / từ chối' : ''} /></label>
      <div className="modal-foot">
        <button onClick={onClose}>Đóng</button>
        {isApproval ? (
          <>
            <button className="danger" onClick={() => submit('rejected')}>✕ Từ chối</button>
            <button className="primary" onClick={() => submit('approved')}>✓ Phê duyệt</button>
          </>
        ) : <button className="primary" onClick={() => submit('done')}>✓ Hoàn thành</button>}
      </div>
    </Modal>
  )
}

function AssigneeFields({ form, setForm, users, agents }) {
  return (
    <div className="grid-2">
      <label>Giao cho người dùng
        <select value={form.assigned_user_id} onChange={(e) => setForm({ ...form, assigned_user_id: e.target.value })}>
          <option value="">— không —</option>
          {users.filter((u) => u.is_active).map((u) => <option key={u.id} value={u.id}>{u.full_name} ({u.role})</option>)}
        </select>
      </label>
      <label>Giao cho AI Agent (FR4.2)
        <select value={form.assigned_agent_id} onChange={(e) => setForm({ ...form, assigned_agent_id: e.target.value })}>
          <option value="">— không —</option>
          {agents.filter((a) => a.is_active).map((a) => <option key={a.id} value={a.id}>🤖 {a.name}</option>)}
        </select>
      </label>
    </div>
  )
}

function PriorityDeadline({ form, setForm }) {
  return (
    <div className="grid-2">
      <label>Ưu tiên
        <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
          <option value="low">Thấp</option><option value="medium">Trung bình</option><option value="high">Cao</option>
        </select>
      </label>
      <label>Hạn chót<input type="datetime-local" value={form.deadline} onChange={(e) => setForm({ ...form, deadline: e.target.value })} /></label>
    </div>
  )
}

function CreateTask({ users, agents, onClose, onDone }) {
  const [form, setForm] = useState({ title: '', description: '', assigned_user_id: '', assigned_agent_id: '', priority: 'medium', deadline: '' })
  const [error, setError] = useState(null)
  const save = async () => {
    try {
      await api.post('/api/tasks', {
        ...form,
        assigned_user_id: Number(form.assigned_user_id) || null,
        assigned_agent_id: Number(form.assigned_agent_id) || null,
        deadline: form.deadline || null,
      })
      onDone()
    } catch (e) { setError(e) }
  }
  return (
    <Modal title="Tạo task" onClose={onClose}>
      <Alert error={error} />
      <label>Tiêu đề<input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
      <label>Mô tả (Agent sẽ dùng làm yêu cầu khi được giao)<textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
      <AssigneeFields form={form} setForm={setForm} users={users} agents={agents} />
      <PriorityDeadline form={form} setForm={setForm} />
      <div className="modal-foot"><button onClick={onClose}>Huỷ</button><button className="primary" onClick={save}>Tạo</button></div>
    </Modal>
  )
}

function ReassignDialog({ task, users, agents, onClose, onDone }) {
  const [form, setForm] = useState({
    assigned_user_id: task.assigned_user_id || '',
    assigned_agent_id: task.assigned_agent_id || '',
    priority: task.priority,
    deadline: task.deadline ? task.deadline.slice(0, 16) : '',
  })
  const [error, setError] = useState(null)
  const save = async () => {
    setError(null)
    try {
      const body = {
        assigned_user_id: Number(form.assigned_user_id) || null,
        assigned_agent_id: Number(form.assigned_agent_id) || null,
        priority: form.priority,
        deadline: form.deadline || null,
      }
      // FR4.5: re-assigning a failed manual task re-opens it.
      if (task.status === 'failed') body.status = 'todo'
      await api.put(`/api/tasks/${task.id}`, body)
      onDone()
    } catch (e) { setError(e) }
  }
  return (
    <Modal title={`Giao lại task #${task.id} (FR4.5)`} onClose={onClose}>
      <Alert error={error} />
      <h4>{task.title}</h4>
      <AssigneeFields form={form} setForm={setForm} users={users} agents={agents} />
      <PriorityDeadline form={form} setForm={setForm} />
      {task.status === 'failed' && <p className="small muted">Task đang thất bại sẽ được mở lại (trạng thái “Cần làm”).</p>}
      <div className="modal-foot"><button onClick={onClose}>Huỷ</button><button className="primary" onClick={save}>Lưu</button></div>
    </Modal>
  )
}

const PRIORITY = { low: 'Thấp', medium: 'TB', high: 'Cao' }

export default function TasksPage() {
  const canManage = ['admin', 'manager'].includes(auth.user.role)
  const [params] = useSearchParams()
  const [mine, setMine] = useState(true)
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [deciding, setDeciding] = useState(null)
  const [creating, setCreating] = useState(false)
  const [reassigning, setReassigning] = useState(null)
  const [err, setErr] = useState(null)
  const { data, error, reload } = useAsync(() => api.get(`/api/tasks${qs({ mine, status, page, page_size: 20 })}`), [mine, status, page])
  const users = useAsync(() => (canManage ? api.get('/api/users?page_size=50') : Promise.resolve({ items: [] })), [])
  const agents = useAsync(() => api.get('/api/agents'), [])
  const userList = users.data?.items || []
  const agentList = agents.data || []
  const agentName = (id) => agentList.find((a) => a.id === id)?.name || `Agent #${id}`
  usePolling(reload, 4000, true)
  const focus = Number(params.get('focus'))

  const quick = async (t, newStatus) => {
    setErr(null)
    try { await api.put(`/api/tasks/${t.id}`, { status: newStatus }); reload() } catch (e) { setErr(e) }
  }
  const runAgent = async (t) => {
    setErr(null)
    try { await api.post(`/api/tasks/${t.id}/run-agent`); reload() } catch (e) { setErr(e) }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <h2>Công việc</h2>
        {canManage && <button className="primary" onClick={() => setCreating(true)}>+ Tạo task</button>}
      </div>
      <Card>
        <div className="filters">
          {canManage && (
            <div className="seg">
              <button className={mine ? 'on' : ''} onClick={() => { setMine(true); setPage(1) }}>Của tôi</button>
              <button className={!mine ? 'on' : ''} onClick={() => { setMine(false); setPage(1) }}>Tất cả</button>
            </div>
          )}
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
            <option value="">Mọi trạng thái</option><option value="todo">Cần làm</option><option value="in_progress">Đang xử lý</option>
            <option value="done">Xong</option><option value="failed">Thất bại</option>
          </select>
        </div>
      </Card>
      <Alert error={error || err} onClose={() => setErr(null)} />
      <Card>
        <table>
          <thead><tr><th>#</th><th>Task</th><th>Loại</th><th>Ưu tiên</th><th>Người nhận</th><th>Hạn</th><th>Trạng thái</th><th /></tr></thead>
          <tbody>
            {(data?.items || []).map((t) => {
              const agentTask = t.task_type === 'manual' && t.assigned_agent_id
              return (
                <tr key={t.id} className={t.id === focus ? 'focus' : ''}>
                  <td>#{t.id}</td>
                  <td>
                    <b>{t.title}</b>
                    {t.workflow_run_id && <div className="tiny"><Link to={`/runs/${t.workflow_run_id}`}>Lượt chạy #{t.workflow_run_id}</Link></div>}
                    {t.result?.decision && <div className="tiny muted">Quyết định: {t.result.decision} {t.result.comment ? `– ${t.result.comment}` : ''}</div>}
                    {t.result?.cancelled && <div className="tiny err">{t.result.comment}</div>}
                    {t.result?.executed_by === 'agent' && (
                      <details className="tiny">
                        <summary>🤖 Kết quả của Agent{t.result.error ? ' (lỗi)' : ''}</summary>
                        <div className="output">{t.result.error || t.result.text}</div>
                      </details>
                    )}
                  </td>
                  <td><span className="tag">{t.task_type === 'approval' ? 'Phê duyệt' : t.task_type === 'user' ? 'Bước workflow' : 'Thủ công'}</span></td>
                  <td><span className={`prio prio-${t.priority}`}>{PRIORITY[t.priority]}</span></td>
                  <td>
                    {t.assigned_user_name || (t.assigned_agent_id ? '' : '—')}
                    {t.assigned_agent_id && <div className="tiny">🤖 {agentName(t.assigned_agent_id)}</div>}
                  </td>
                  <td className={`small ${t.is_overdue ? 'err' : ''}`}>{fmtDate(t.deadline)}{t.is_overdue ? ' (quá hạn)' : ''}</td>
                  <td><Badge status={t.status} /></td>
                  <td className="actions">
                    {['todo', 'in_progress'].includes(t.status) && (t.assigned_user_id === auth.user.id || canManage) && !(agentTask && (!t.assigned_user_id || t.result?.agent_running)) && (
                      <>
                        {t.status === 'todo' && t.task_type === 'manual' && <button className="small" onClick={() => quick(t, 'in_progress')}>Bắt đầu</button>}
                        {t.task_type === 'manual'
                          ? <button className="small primary" onClick={() => quick(t, 'done')}>Xong</button>
                          : <button className="small primary" onClick={() => setDeciding(t)}>{t.task_type === 'approval' ? 'Duyệt…' : 'Xử lý…'}</button>}
                      </>
                    )}
                    {canManage && agentTask && ['todo', 'failed'].includes(t.status) && (
                      <button className="small primary" onClick={() => runAgent(t)}>🤖 {t.status === 'failed' ? 'Chạy lại' : 'Chạy'} bằng Agent</button>
                    )}
                    {agentTask && t.status === 'in_progress' && t.result?.agent_running && <span className="tiny muted">Agent đang xử lý…</span>}
                    {canManage && t.task_type === 'manual' && t.status !== 'done' && t.status !== 'in_progress' && (
                      <button className="small" onClick={() => setReassigning(t)}>Giao lại…</button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {data && <Pager page={page} pageSize={20} total={data.total} onPage={setPage} />}
      </Card>
      {deciding && <DecideDialog task={deciding} onClose={() => setDeciding(null)} onDone={() => { setDeciding(null); reload() }} />}
      {creating && <CreateTask users={userList} agents={agentList} onClose={() => setCreating(false)} onDone={() => { setCreating(false); reload() }} />}
      {reassigning && (
        <ReassignDialog task={reassigning} users={userList} agents={agentList}
          onClose={() => setReassigning(null)} onDone={() => { setReassigning(null); reload() }} />
      )}
    </div>
  )
}
