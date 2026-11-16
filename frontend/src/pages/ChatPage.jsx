import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Alert, Empty, useAsync } from '../components/ui'

// Each question starts a run of a chat workflow (goes through the Coordinator, retry and
// audit like every other execution); the page polls the run until it is final.
export default function ChatPage() {
  const { data: workflows, error } = useAsync(() => api.get('/api/workflows?chat_only=true'), [])
  const [workflowId, setWorkflowId] = useState(null)
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const bottom = useRef(null)

  useEffect(() => {
    if (workflows?.length && !workflowId) setWorkflowId(workflows[0].id)
  }, [workflows, workflowId])

  useEffect(() => {
    if (!workflowId) return
    api.get(`/api/chat/history?workflow_id=${workflowId}`).then(setMessages).catch(setErr)
  }, [workflowId])

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const poll = async (runId) => {
    for (let i = 0; i < 240; i += 1) {
      await new Promise((r) => setTimeout(r, 1000))
      const run = await api.get(`/api/workflow-runs/${runId}`)
      const step = run.steps[0]
      setMessages((ms) => ms.map((m) => (m.run_id === runId
        ? { ...m, status: run.status, answer: run.final_result?.text, sources: run.final_result?.sources || [],
            error_message: run.error_message, retry_count: step?.retry_count, step_id: step?.id }
        : m)))
      if (run.status !== 'running') return
    }
  }

  const ask = async (e) => {
    e.preventDefault()
    const q = question.trim()
    if (!q || !workflowId) return
    setBusy(true)
    setErr(null)
    try {
      const res = await api.post('/api/chat/ask', { workflow_id: workflowId, question: q })
      setMessages((ms) => [...ms, { run_id: res.run_id, question: q, status: 'running', sources: [] }])
      setQuestion('')
      await poll(res.run_id)
    } catch (ex) {
      setErr(ex)
    } finally {
      setBusy(false)
    }
  }

  const retry = async (m) => {
    setErr(null)
    try {
      await api.post(`/api/step-runs/${m.step_id}/retry`)
      setMessages((ms) => ms.map((x) => (x.run_id === m.run_id ? { ...x, status: 'running', error_message: null } : x)))
      await poll(m.run_id)
    } catch (ex) { setErr(ex) }
  }

  if (error) return <Alert error={error} />
  return (
    <div className="chat-page">
      <div className="page-head">
        <h2>Chat hỏi đáp</h2>
        <select value={workflowId || ''} onChange={(e) => setWorkflowId(Number(e.target.value))}>
          {(workflows || []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
        </select>
      </div>
      <p className="muted small">Trợ lý trả lời dựa trên kho tri thức nội bộ (RAG) và trích dẫn nguồn. Mỗi câu hỏi là một lượt chạy workflow, có retry tự động và được ghi nhật ký.</p>
      <Alert error={err} onClose={() => setErr(null)} />
      <div className="chat-box">
        {messages.length === 0 && <Empty>Hãy thử: “Nhân viên được nghỉ phép năm bao nhiêu ngày?” hoặc “Làm thêm giờ ngày lễ được trả bao nhiêu?”</Empty>}
        {messages.map((m) => (
          <div key={m.run_id} className="chat-turn">
            <div className="bubble user">{m.question}</div>
            <div className={`bubble bot ${m.status === 'failed' ? 'bot-failed' : ''}`}>
              {m.status === 'running' && <span className="typing">Agent đang tra cứu tài liệu và soạn câu trả lời<span>…</span></span>}
              {m.status === 'completed' && <div className="answer">{m.answer}</div>}
              {m.status === 'failed' && (
                <div>
                  <b>Không trả lời được.</b> <span className="small">{m.error_message}</span>
                  {m.step_id && <div><button className="small" onClick={() => retry(m)}>↻ Thử lại bước lỗi</button></div>}
                </div>
              )}
              {m.sources?.length > 0 && (
                <details className="sources">
                  <summary>📎 {m.sources.length} nguồn tham khảo</summary>
                  {m.sources.map((s) => (
                    <div key={`${s.ref}-${s.chunk_index}`} className="source">
                      <b>[Nguồn {s.ref}] {s.heading || s.document}</b> <span className="tiny muted">({s.document} · điểm BM25 {s.score})</span>
                      <div className="small">{s.excerpt}…</div>
                    </div>
                  ))}
                </details>
              )}
              <div className="tiny muted">
                <Link to={`/runs/${m.run_id}`}>Lượt chạy #{m.run_id}</Link>
                {m.retry_count ? ' · đã tự retry 1 lần' : ''}
              </div>
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>
      <form className="chat-input" onSubmit={ask}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Nhập câu hỏi về nội quy công ty…" disabled={busy} />
        <button className="primary" disabled={busy || !question.trim()}>{busy ? 'Đang xử lý…' : 'Gửi'}</button>
      </form>
    </div>
  )
}
