import { useState } from 'react'
import { api } from '../api'
import { Alert, Card, Modal, fmtDate, useAsync } from '../components/ui'

export default function KnowledgePage() {
  const collections = useAsync(() => api.get('/api/knowledge/collections'), [])
  const docs = useAsync(() => api.get('/api/knowledge/documents'), [])
  const [file, setFile] = useState(null)
  const [collection, setCollection] = useState('noi-quy')
  const [title, setTitle] = useState('')
  const [err, setErr] = useState(null)
  const [ok, setOk] = useState(null)
  const [query, setQuery] = useState('nghỉ phép năm bao nhiêu ngày')
  const [searchCol, setSearchCol] = useState('noi-quy')
  const [hits, setHits] = useState(null)
  const [viewing, setViewing] = useState(null)

  const upload = async (e) => {
    e.preventDefault()
    if (!file) return
    setErr(null)
    const form = new FormData()
    form.append('file', file)
    form.append('collection', collection)
    if (title) form.append('title', title)
    try {
      const d = await api.upload('/api/knowledge/documents', form)
      setOk(`Đã nạp "${d.title}": ${d.char_count.toLocaleString('vi-VN')} ký tự → ${d.chunk_count} đoạn (chunk).`)
      setFile(null)
      setTitle('')
      docs.reload()
      collections.reload()
    } catch (ex) { setErr(ex) }
  }

  const search = async (e) => {
    e.preventDefault()
    try { setHits(await api.get(`/api/knowledge/search?collection=${encodeURIComponent(searchCol)}&q=${encodeURIComponent(query)}`)) } catch (ex) { setErr(ex) }
  }

  const remove = async (d) => {
    if (!window.confirm(`Gỡ tài liệu "${d.title}" khỏi kho tri thức?`)) return
    try { await api.del(`/api/knowledge/documents/${d.id}`); docs.reload(); collections.reload() } catch (ex) { setErr(ex) }
  }

  return (
    <div className="stack">
      <div className="page-head"><h2>Kho tri thức (RAG)</h2></div>
      <p className="small muted">Tài liệu được cắt thành đoạn theo Chương/Điều, sau đó tìm bằng BM25 (chạy offline, không cần GPU). Agent gắn với một bộ tri thức sẽ đưa các đoạn liên quan nhất vào prompt và trích dẫn [Nguồn n].</p>
      <Alert error={err} onClose={() => setErr(null)} />
      {ok && <Alert error={ok} kind="ok" onClose={() => setOk(null)} />}
      <div className="grid-2">
        <Card title="Nạp tài liệu (.txt, .md, .pdf, .docx)">
          <form onSubmit={upload} className="stack">
            <input type="file" accept=".txt,.md,.pdf,.docx" onChange={(e) => setFile(e.target.files[0])} />
            <div className="grid-2">
              <label>Bộ tri thức<input value={collection} onChange={(e) => setCollection(e.target.value)} placeholder="vd: noi-quy" /></label>
              <label>Tiêu đề (tuỳ chọn)<input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
            </div>
            <button className="primary" disabled={!file}>⬆ Nạp tài liệu</button>
          </form>
        </Card>
        <Card title="Thử truy xuất (retrieval)">
          <form onSubmit={search} className="row">
            <select value={searchCol} onChange={(e) => setSearchCol(e.target.value)}>
              {(collections.data || []).map((c) => <option key={c.name}>{c.name}</option>)}
            </select>
            <input className="grow" value={query} onChange={(e) => setQuery(e.target.value)} />
            <button>Tìm</button>
          </form>
          {hits && hits.length === 0 && <div className="muted small">Không có đoạn nào khớp.</div>}
          {hits?.map((h, i) => (
            <div key={i} className="source small"><b>#{i + 1} {h.heading}</b> <span className="tiny muted">điểm {h.score}</span><div>{h.content.slice(0, 260)}…</div></div>
          ))}
        </Card>
      </div>
      <Card title="Tài liệu">
        <table>
          <thead><tr><th>Tài liệu</th><th>Bộ tri thức</th><th>Ký tự</th><th>Số đoạn</th><th>Nạp lúc</th><th /></tr></thead>
          <tbody>
            {(docs.data || []).map((d) => (
              <tr key={d.id}>
                <td><b>{d.title}</b><div className="tiny muted">{d.filename}</div></td>
                <td><span className="tag">{d.collection}</span></td>
                <td>{d.char_count.toLocaleString('vi-VN')}</td><td>{d.chunk_count}</td>
                <td className="small">{fmtDate(d.created_at)}</td>
                <td className="actions">
                  <button className="small" onClick={async () => setViewing(await api.get(`/api/knowledge/documents/${d.id}`))}>Xem đoạn</button>
                  <button className="small danger" onClick={() => remove(d)}>Gỡ</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {viewing && (
        <Modal title={`${viewing.document.title} – ${viewing.chunks.length} đoạn`} onClose={() => setViewing(null)} wide>
          <div className="chunks">
            {viewing.chunks.map((c) => (
              <div key={c.chunk_index} className="source small"><b>Đoạn {c.chunk_index + 1}{c.heading ? ` · ${c.heading}` : ''}</b><div className="pre">{c.content}</div></div>
            ))}
          </div>
        </Modal>
      )}
    </div>
  )
}
