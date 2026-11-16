import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, auth } from '../api'
import { Alert } from '../components/ui'

const DEMO = [
  ['admin@company.local', 'Admin@123', 'Admin'],
  ['manager@company.local', 'Manager@123', 'Manager'],
  ['employee@company.local', 'Employee@123', 'Employee'],
]

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  const login = async (e, preset) => {
    e?.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const body = preset ? { email: preset[0], password: preset[1] } : { email, password }
      const res = await api.post('/api/auth/login', body)
      auth.save(res.access_token, res.user)
      navigate(location.state?.from?.pathname || '/', { replace: true })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={login}>
        <div className="login-logo">🤖</div>
        <h2>Multi-Agent AI Platform</h2>
        <p className="muted">Tự động hoá quy trình & điều phối công việc</p>
        <Alert error={error} />
        <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email@company.local" autoFocus /></label>
        <label>Mật khẩu<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <button className="primary" disabled={busy}>{busy ? 'Đang đăng nhập…' : 'Đăng nhập'}</button>
        <div className="demo-accounts">
          <span className="tiny muted">Tài khoản demo:</span>
          {DEMO.map((d) => (
            <button type="button" key={d[0]} className="ghost small" onClick={(e) => login(e, d)}>{d[2]}</button>
          ))}
        </div>
      </form>
    </div>
  )
}
