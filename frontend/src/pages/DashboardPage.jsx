import { Link } from 'react-router-dom'
import { api, auth } from '../api'
import { Alert, Badge, Card, fmtDate, useAsync, usePolling } from '../components/ui'

function Kpi({ label, value, tone, hint }) {
  return (
    <div className={`kpi kpi-${tone || 'default'}`}>
      <div className="kpi-value">{value ?? '—'}</div>
      <div className="kpi-label">{label}</div>
      {hint && <div className="tiny muted">{hint}</div>}
    </div>
  )
}

export default function DashboardPage() {
  const { data, error, reload } = useAsync(() => api.get('/api/dashboard/summary'), [])
  usePolling(reload, 5000, true)
  const user = auth.user
  if (error) return <Alert error={error} />
  if (!data) return <div className="muted">Đang tải…</div>
  const max = Math.max(1, ...data.runs_per_day.map((d) => d.total))

  return (
    <div className="stack">
      <div className="page-head">
        <h2>Tổng quan {data.scope === 'mine' ? '(của tôi)' : 'hệ thống'}</h2>
        <span className="muted">Xin chào {user.full_name} · cập nhật tự động mỗi 5 giây</span>
      </div>
      <div className="kpis">
        <Kpi label="Tổng lượt chạy" value={data.runs.total.toLocaleString('vi-VN')} />
        <Kpi label="Đang chạy" value={data.runs.running} tone="info" />
        <Kpi label="Chờ người xử lý" value={data.runs.waiting_for_human} tone="warn" />
        <Kpi label="Hoàn thành" value={data.runs.completed.toLocaleString('vi-VN')} tone="ok" />
        <Kpi label="Thất bại" value={data.runs.failed.toLocaleString('vi-VN')} tone="bad" />
        <Kpi label="Tỉ lệ thành công" value={data.runs.success_rate != null ? `${data.runs.success_rate}%` : '—'} tone="ok" />
        <Kpi label="Task cần làm" value={data.tasks.todo + data.tasks.in_progress} tone="info" hint={`${data.tasks.overdue} quá hạn`} />
      </div>

      <div className="grid-2">
        <Card title="Lượt chạy 14 ngày gần nhất">
          {data.runs_per_day.length === 0 && <div className="muted">Chưa có dữ liệu</div>}
          <div className="bars">
            {data.runs_per_day.map((d) => (
              <div className="bar-col" key={d.day} title={`${d.day}: ${d.completed} hoàn thành, ${d.failed} thất bại`}>
                <div className="bar-stack" style={{ height: `${(d.total / max) * 140}px` }}>
                  <div className="bar-failed" style={{ flex: d.failed }} />
                  <div className="bar-ok" style={{ flex: d.total - d.failed }} />
                </div>
                <div className="tiny muted">{d.day.slice(5)}</div>
              </div>
            ))}
          </div>
          <div className="legend tiny"><span className="sw sw-ok" /> hoàn thành / khác <span className="sw sw-bad" /> thất bại</div>
        </Card>
        <Card title="Lỗi gần đây" actions={<Link to="/history?status=failed">Xem tất cả</Link>}>
          {data.recent_failures.length === 0 && <div className="muted">Không có lỗi 🎉</div>}
          {data.recent_failures.map((f) => (
            <Link to={`/runs/${f.run_id}`} key={f.run_id} className="fail-row">
              <b>#{f.run_id} {f.workflow_name}</b>
              <span className="small err">{f.error_message}</span>
              <span className="tiny muted">{fmtDate(f.finished_at)}</span>
            </Link>
          ))}
        </Card>
      </div>

      {data.agents.length > 0 && (
        <Card title="Trạng thái AI Agent (FR7.1)">
          <table>
            <thead><tr><th>Agent</th><th>Trạng thái</th><th>Số bước đã chạy</th><th>Thành công</th><th>Thất bại</th><th>Kết quả gần nhất</th><th>Lần chạy cuối</th></tr></thead>
            <tbody>
              {data.agents.map((a) => (
                <tr key={a.id}>
                  <td>{a.name}</td>
                  <td><Badge status={a.is_active ? 'active' : 'inactive'} /></td>
                  <td>{a.total_runs}</td><td>{a.done}</td><td>{a.failed}</td>
                  <td>{a.last_status ? <Badge status={a.last_status} /> : '—'}</td>
                  <td className="small">{fmtDate(a.last_run_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {data.workflows.length > 0 && (
        <Card title="Workflow được dùng nhiều nhất">
          <table>
            <thead><tr><th>Workflow</th><th>Tổng</th><th>Hoàn thành</th><th>Thất bại</th></tr></thead>
            <tbody>{data.workflows.map((w) => <tr key={w.id}><td>{w.name}</td><td>{w.total}</td><td>{w.completed}</td><td>{w.failed}</td></tr>)}</tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
