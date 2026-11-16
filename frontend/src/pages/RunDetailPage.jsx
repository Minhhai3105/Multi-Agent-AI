import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { Alert, Badge, Card, Json, STEP_LABEL, duration, fmtDate, useAsync, usePolling } from '../components/ui'

function StepCard({ step, onRetry, busy }) {
  const out = step.output_result || {}
  return (
    <div className={`step step-${step.status}`}>
      <div className="step-head">
        <span className="step-no">{step.step_order}</span>
        <div className="grow">
          <b>{step.name}</b>
          <div className="tiny muted">
            {STEP_LABEL[step.step_type]}{step.agent_name ? ` · ${step.agent_name}` : ''}
            {step.assigned_user_name ? ` · giao cho ${step.assigned_user_name}` : ''}
            {out.provider ? ` · ${out.provider}/${out.model}` : ''}
            {step.started_at ? ` · ${duration(step.started_at, step.finished_at)}` : ''}
          </div>
        </div>
        {step.retry_count > 0 && <span className="tag tag-warn" title="QA-1: retry tự động đúng 1 lần">auto-retry ×{step.retry_count}</span>}
        {out.manual_retry && <span className="tag tag-warn" title="QA-4: chỉ bước lỗi được chạy lại">retry thủ công</span>}
        <Badge status={step.status} />
      </div>
      {step.status === 'in_progress' && ['user', 'approval'].includes(step.step_type) && (
        <div className="alert alert-warn small">⏸ Đang chờ người xử lý task – không chiếm luồng nào (D06). <Link to="/tasks">Mở danh sách task</Link></div>
      )}
      {step.error_message && (
        <div className="alert alert-error small">
          <span>{step.error_message}</span>
          {step.status === 'failed' && <button className="small" disabled={busy} onClick={() => onRetry(step)}>↻ Retry bước này (UC-07)</button>}
        </div>
      )}
      {out.manual_retry && (
        <div className="alert alert-warn small">↻ Bước này được {out.manual_retry.retried_by} retry thủ công từ input_context đã lưu. Lỗi trước đó: {out.manual_retry.previous_error}</div>
      )}
      {out.attempts?.length > 0 && (
        <div className="attempts tiny">
          {out.attempts.map((a) => (
            <span key={a.attempt} className={a.ok ? 'att-ok' : 'att-bad'}>Lần {a.attempt}: {a.ok ? `OK (${a.latency_ms} ms)` : `${a.error}`}</span>
          ))}
        </div>
      )}
      {out.text && <div className="output">{out.text}</div>}
      {out.sources?.length > 0 && (
        <details className="sources"><summary>📎 {out.sources.length} nguồn tri thức (RAG)</summary>
          {out.sources.map((s) => <div key={s.ref} className="source small"><b>[Nguồn {s.ref}] {s.heading}</b> – {s.excerpt}…</div>)}
        </details>
      )}
      <details className="tiny"><summary>Input context (đã lưu – dùng khi retry)</summary><Json value={step.input_context} /></details>
    </div>
  )
}

export default function RunDetailPage() {
  const { id } = useParams()
  const { data: run, error, reload } = useAsync(() => api.get(`/api/workflow-runs/${id}`), [id])
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  usePolling(reload, 1500, run?.status === 'running')

  const retry = async (step) => {
    setBusy(true)
    setErr(null)
    try {
      await api.post(`/api/step-runs/${step.id}/retry`)
      await reload()
    } catch (e) { setErr(e) } finally { setBusy(false) }
  }

  if (error) return <Alert error={error} />
  if (!run) return <div className="muted">Đang tải…</div>
  const done = run.steps.filter((s) => s.status === 'done').length
  return (
    <div className="stack">
      <div className="page-head">
        <h2>Lượt chạy #{run.id} · {run.workflow_name}</h2>
        <Badge status={run.status} />
      </div>
      <div className="progress"><div style={{ width: `${(done / run.steps.length) * 100}%` }} /></div>
      <div className="meta small muted">
        Bởi {run.started_by_name} · bắt đầu {fmtDate(run.started_at)} · {run.finished_at ? `kết thúc ${fmtDate(run.finished_at)} (${duration(run.started_at, run.finished_at)})` : 'đang chạy – tự cập nhật 1,5 s/lần (polling)'}
      </div>
      <Alert error={err} onClose={() => setErr(null)} />
      {run.error_message && <div className="alert alert-error">{run.error_message}</div>}
      <div className="grid-run">
        <div className="stack">
          {run.steps.map((s) => <StepCard key={s.id} step={s} onRetry={retry} busy={busy} />)}
        </div>
        <div className="stack">
          <Card title="Đầu vào"><Json value={run.initial_input} /></Card>
          {run.final_result && <Card title="Kết quả cuối (FR5.4)"><div className="output">{run.final_result.text}</div></Card>}
          {run.tasks.length > 0 && (
            <Card title="Task liên quan">
              {run.tasks.map((t) => (
                <div key={t.id} className="task-mini">
                  <Badge status={t.status} /> <b>#{t.id}</b> {t.title}
                  <div className="tiny muted">Giao cho {t.assigned_user_name} {t.result?.decision ? `· ${t.result.decision}` : ''}</div>
                </div>
              ))}
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
