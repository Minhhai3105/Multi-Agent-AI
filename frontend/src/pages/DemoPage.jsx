import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Alert, Card, useAsync } from '../components/ui'

const PROVIDER_LABEL = {
  gemini: 'Google Gemini (API trực tiếp)',
  openai_compatible: 'OpenAI-compatible gateway (vd. CLIProxyAPI)',
  mock: 'Mock (mô phỏng, không cần API key)',
}

const SCENARIOS = [
  {
    id: 'QA-1', title: 'Reliability – LLM lỗi tạm thời được retry tự động 1 lần',
    steps: ['Bấm "Lỗi 1 lần" bên dưới.', 'Chạy workflow "Soạn nội dung marketing".', 'Mở lượt chạy: bước 1 có nhãn auto-retry ×1, lần 1 lỗi, lần 2 OK; workflow vẫn hoàn thành.'],
    fault: { mode: 'fail_next', count: 1 },
  },
  {
    id: 'QA-1 / QA-4', title: 'Lỗi kéo dài ở bước 2 → giữ kết quả bước 1 → retry thủ công',
    steps: ['Bấm "Lỗi từ bước 2".', 'Chạy workflow marketing: bước 1 xong, bước 2 thất bại sau đúng 1 lần retry, bước 3 vẫn chờ.', 'Bấm "Tắt giả lập lỗi" rồi bấm "Retry bước này" ở bước 2: chỉ bước 2, 3 chạy lại, bước 1 giữ nguyên.'],
    fault: { mode: 'fail_always', count: 0, skip: 1 },
  },
  {
    id: 'QA-1', title: 'Timeout của nhà cung cấp LLM',
    steps: ['Bấm "Timeout 2 lần".', 'Chạy workflow bất kỳ: bước 1 báo lỗi timeout sau 1 lần retry, lỗi được lưu trong error_message.'],
    fault: { mode: 'timeout_next', count: 2 },
  },
  {
    id: 'QA-3', title: 'Performance – bắt đầu workflow trả 202 ngay cả khi LLM chậm',
    steps: ['Đặt độ trễ LLM mô phỏng = 5000 ms.', 'Chạy workflow: hộp thoại báo HTTP 202 + run_id sau vài chục ms; các bước vẫn tiếp tục chạy nền.'],
  },
  {
    id: 'R01', title: 'Khôi phục sau khi backend khởi động lại',
    steps: ['Đặt độ trễ 15000 ms rồi chạy workflow marketing.', 'Khi bước 1 đang chạy: chạy lệnh "docker compose restart app".', 'Mở lại lượt chạy: bước 1 failed với lỗi "interrupted", bấm Retry để hoàn thành. Lượt chạy đang chờ phê duyệt KHÔNG bị ảnh hưởng.'],
  },
]

export default function DemoPage() {
  const { data, error, reload, setData } = useAsync(() => api.get('/api/demo/info'), [])
  const [latency, setLatency] = useState('')
  const [err, setErr] = useState(null)

  const setFault = async (body) => {
    setErr(null)
    try { setData(await api.put('/api/demo/llm-fault', { count: 1, kind: 'provider_error', skip: 0, ...body })) } catch (e) { setErr(e) }
  }
  const setLat = async (ms) => {
    setErr(null)
    try { setData(await api.put('/api/demo/mock-latency', { latency_ms: Number(ms) })); setLatency('') } catch (e) { setErr(e) }
  }

  if (error) return <Alert error={error} />
  if (!data) return null
  const f = data.fault
  return (
    <div className="stack">
      <div className="page-head"><h2>Bảng điều khiển Demo – kịch bản thuộc tính chất lượng</h2></div>
      <Alert error={err} onClose={() => setErr(null)} />
      <div className="grid-2">
        <Card title="LLM Client">
          <p>Nhà cung cấp: <b>{PROVIDER_LABEL[data.provider] || data.provider}</b> · model mặc định <code>{data.default_model}</code></p>
          {data.base_url && <p className="small">Địa chỉ: <code>{data.base_url}</code> · API key: {data.api_key_configured ? 'đã cấu hình' : <b className="err">chưa cấu hình</b>}</p>}
          <p className="small">Timeout LLM: {data.llm_timeout_seconds} s · retry tự động: đúng 1 lần cho lỗi tạm thời (timeout, 429, 5xx)</p>
          {data.mock_latency_ms !== null && (
            <div className="row">
              <span>Độ trễ mô phỏng: <b>{data.mock_latency_ms} ms</b></span>
              <input type="number" placeholder="ms" value={latency} onChange={(e) => setLatency(e.target.value)} style={{ width: 100 }} />
              <button onClick={() => setLat(latency)} disabled={latency === ''}>Đặt</button>
              <button onClick={() => setLat(800)}>800</button><button onClick={() => setLat(5000)}>5000</button><button onClick={() => setLat(15000)}>15000</button>
            </div>
          )}
        </Card>
        <Card title="Giả lập lỗi (Fault injection – risk R02)" actions={<button className="small" onClick={reload}>↻</button>}>
          {f ? (
            <>
              <p>Trạng thái: <b className={f.mode === 'none' ? 'ok' : 'err'}>{f.mode}</b>
                {f.mode !== 'none' && <> · còn {f.remaining} lần · bỏ qua {f.skip} lượt đầu · kiểu {f.kind}</>}
                <span className="muted small"> · đã gây {f.injected_total} lỗi</span></p>
              <div className="row wrap">
                <button onClick={() => setFault({ mode: 'fail_next', count: 1 })}>Lỗi 1 lần</button>
                <button onClick={() => setFault({ mode: 'fail_always', count: 0, skip: 1 })}>Lỗi từ bước 2</button>
                <button onClick={() => setFault({ mode: 'fail_next', count: 2, kind: 'rate_limit' })}>429 × 2</button>
                <button onClick={() => setFault({ mode: 'timeout_next', count: 2 })}>Timeout 2 lần</button>
                <button className="primary" onClick={() => setFault({ mode: 'none', count: 0 })}>Tắt giả lập lỗi</button>
              </div>
            </>
          ) : <p className="muted">DEMO_MODE đang tắt.</p>}
        </Card>
      </div>
      {SCENARIOS.map((s) => (
        <Card key={s.title} title={<><span className="tag">{s.id}</span> {s.title}</>}
          actions={s.fault && <button className="small" onClick={() => setFault(s.fault)}>Bật lỗi cho kịch bản</button>}>
          <ol className="small">{s.steps.map((x) => <li key={x}>{x}</li>)}</ol>
        </Card>
      ))}
      <Card title="Các kịch bản khác">
        <ul className="small">
          <li><b>QA-2</b>: đăng nhập Employee và mở <code>/agents</code>, hoặc gọi API quản trị → 403. Gọi API không có token → 401.</li>
          <li><b>QA-5</b>: mở <Link to="/history">Lịch sử</Link>; chip ⏱ hiện thời gian truy vấn của server (đã thử với ~10.000 bản ghi step).</li>
          <li><b>QA-6</b>: mở <Link to="/activity-logs">Nhật ký hoạt động</Link> sau mỗi thao tác.</li>
          <li><b>FR4</b>: Employee chạy “Xử lý đơn xin nghỉ phép” → Manager duyệt ở <Link to="/tasks">Công việc</Link> → workflow tự chạy tiếp.</li>
        </ul>
      </Card>
    </div>
  )
}
