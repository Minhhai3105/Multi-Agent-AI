import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, qs } from '../api'
import { Alert, Badge, Card, Pager, duration, fmtDate, useAsync } from '../components/ui'

export default function HistoryPage() {
  const [params] = useSearchParams()
  const [filters, setFilters] = useState({ workflow_id: '', status: params.get('status') || '', date_from: '', date_to: '', mine: false })
  const [page, setPage] = useState(1)
  const pageSize = 20
  const workflows = useAsync(() => api.get('/api/workflows'), [])
  const { data: res, error, loading } = useAsync(
    () => api.timed(`/api/history${qs({ ...filters, mine: filters.mine || undefined, page, page_size: pageSize })}`),
    [JSON.stringify(filters), page],
  )
  const data = res?.data
  const set = (patch) => { setFilters({ ...filters, ...patch }); setPage(1) }
  const last = res && !Number.isNaN(res.serverMs) ? res : null

  return (
    <div className="stack">
      <div className="page-head">
        <h2>Lịch sử chạy workflow</h2>
        {last && <span className={`rt-chip ${last.serverMs > 2000 ? 'rt-slow' : ''}`}>QA-5: truy vấn {last.serverMs.toFixed(0)} ms (mục tiêu ≤ 2000 ms, trang ≤ 50 bản ghi)</span>}
      </div>
      <Card>
        <div className="filters">
          <select value={filters.workflow_id} onChange={(e) => set({ workflow_id: e.target.value })}>
            <option value="">Tất cả workflow</option>
            {(workflows.data || []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
          <select value={filters.status} onChange={(e) => set({ status: e.target.value })}>
            <option value="">Mọi trạng thái</option>
            <option value="running">Đang chạy</option><option value="completed">Hoàn thành</option><option value="failed">Thất bại</option>
          </select>
          <label className="inline">Từ <input type="date" value={filters.date_from} onChange={(e) => set({ date_from: e.target.value })} /></label>
          <label className="inline">Đến <input type="date" value={filters.date_to} onChange={(e) => set({ date_to: e.target.value ? `${e.target.value}T23:59:59` : '' })} /></label>
          <label className="check"><input type="checkbox" checked={filters.mine} onChange={(e) => set({ mine: e.target.checked })} /> Chỉ của tôi</label>
        </div>
      </Card>
      <Alert error={error} />
      <Card>
        <table>
          <thead><tr><th>#</th><th>Workflow</th><th>Đầu vào</th><th>Người chạy</th><th>Trạng thái</th><th>Bắt đầu</th><th>Thời lượng</th><th>Lỗi</th></tr></thead>
          <tbody>
            {(data?.items || []).map((r) => (
              <tr key={r.id}>
                <td><Link to={`/runs/${r.id}`}>#{r.id}</Link></td>
                <td>{r.workflow_name}</td>
                <td className="small">{r.input_preview}</td>
                <td>{r.started_by_name}</td>
                <td><Badge status={r.status} /></td>
                <td className="small">{fmtDate(r.started_at)}</td>
                <td className="small">{duration(r.started_at, r.finished_at)}</td>
                <td className="small err">{r.error_message}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && <div className="muted pad">Đang tải…</div>}
        {data && <Pager page={page} pageSize={pageSize} total={data.total} onPage={setPage} />}
      </Card>
    </div>
  )
}
