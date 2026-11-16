# Multi-Agent AI Platform

**Design and Development of a Multi-Agent AI Platform for Business Process Automation and Work Coordination**
Capstone C1SE.41 · Duy Tan University · Software Architecture & Design

A configurable platform where several AI Agents and people work through one ordered
workflow. AI Agents are configuration rows (role, instruction, model) on top of one LLM
provider (Google Gemini). The platform does not train a model. Human steps (approval or user
input) become tasks, and the run resumes when the task is finished. Agents can answer
from internal documents through RAG, for example the company policy.

Architecture follows *Architecture Design Document v1.5*:
- a layered FastAPI modular monolith (React SPA, FastAPI backend, PostgreSQL);
- one Workflow Coordinator and one LLM Client adapter;
- JWT + RBAC and an audit log.

---

## 1. Chạy nhanh bằng Docker (khuyên dùng khi demo)

Yêu cầu: Docker Desktop.

```bash
cp .env.example .env          # sửa GEMINI_API_KEY nếu muốn dùng Gemini thật
docker compose up --build
```

Mở trình duyệt tại http://localhost:8000.

| Vai trò | Email | Mật khẩu |
|---|---|---|
| Admin | admin@company.local | Admin@123 |
| Manager | manager@company.local | Manager@123 |
| Employee | employee@company.local | Employee@123 |
| Employee 2 | employee2@company.local | Employee@123 |

Nếu `GEMINI_API_KEY` để trống, hệ thống dùng **LLM mô phỏng (mock)**: chạy offline, không tốn quota.
Khi điền key Google AI Studio, hệ thống tự gọi Gemini. Nếu dùng proxy như CLIProxyAPI, xem mục bên dưới.
Key chỉ nằm trong `.env` (quy tắc R6), không có trong code hay database.

### Dùng CLIProxyAPI hoặc gateway OpenAI-compatible

Key CLIProxyAPI là *client access key* do proxy tự kiểm tra, không phải key Google. Vì vậy dùng chế độ `openai_compatible`. Cách gọi giống dự án secretary-schedule: `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL` bên đó tương ứng với `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` ở đây.

Trong `.env`:

```
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://host.docker.internal:8317/v1
LLM_API_KEY=<client access key của CLIProxyAPI>
LLM_MODEL=<một id trong GET /v1/models>
LLM_TIMEOUT_SECONDS=120
LLM_MAX_OUTPUT_TOKENS=0
```

Chạy trong Docker thì phải dùng `host.docker.internal`, vì `127.0.0.1` bên trong container là chính container.

Kiểm tra kết nối **từ bên trong container** trước khi chạy workflow. Script liệt kê model, kiểm tra `LLM_MODEL` có trong danh sách và gửi thử một câu; key không bao giờ được in ra:

```bash
docker compose run --rm app python scripts/check_llm_connection.py
```

| Script báo | Cách xử lý |
|---|---|
| `provider_error: Không kết nối được …` | Proxy chưa chạy, sai cổng, hoặc container không tới được host. Docker Desktop (macOS/Windows) thường tới được proxy chỉ nghe ở `127.0.0.1`. Linux thì không: cần cho proxy nghe ở địa chỉ mà Docker tới được, và chặn cổng đó với mạng ngoài. |
| `config_error … HTTP 401` | Sai `LLM_API_KEY`. |
| `LLM_MODEL=… không có trong danh sách` | Chọn một id trong danh sách script in ra. |
| `timeout` | Tăng `LLM_TIMEOUT_SECONDS`, vì model thinking chạy chậm. |
| `LLM_MODEL chưa đặt` | Điền một id trong danh sách script in ra. |

Agent nào có model là `default` thì dùng model trong `.env`, nên đổi model chỉ cần sửa `.env` rồi chạy lại `docker compose up -d --force-recreate app`. Nếu proxy lỗi trong lúc demo, đặt `LLM_PROVIDER=mock` để chạy tiếp bằng LLM mô phỏng.

### Xem database bằng DBeaver

`docker compose` mở cổng PostgreSQL ra máy:

| Thông số | Giá trị |
|---|---|
| Host | `localhost` |
| Port | `5432` (đổi bằng `DB_PORT` trong `.env` nếu máy đã có PostgreSQL) |
| Database | `maap` |
| Username | `maap` |
| Password | `maap_dev_password` |

Trong DBeaver, chọn *New Database Connection → PostgreSQL*, rồi điền các thông số trên. Muốn xem sơ đồ quan hệ thì
chọn schema `public`, chuột phải, chọn *View Diagram*. File `database/schema.sql` chứa DDL của 11 bảng và các index.

## 2. Chạy không cần Docker (khi phát triển)

Yêu cầu: Python 3.12+, Node 20+, PostgreSQL 16.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/maap
uvicorn app.main:app --reload --port 8000
```

```bash
# Frontend (cửa sổ khác) – http://localhost:5173, tự proxy /api sang :8000
cd frontend
npm install
npm run dev
```

Lệnh `npm run build` build SPA vào `backend/static`. Sau đó FastAPI phục vụ cả giao diện lẫn API trên cổng 8000.

## 3. Kiểm thử và đo thuộc tính chất lượng

```bash
cd backend
createdb maap_test                                   # database riêng cho test (bị xoá/tạo lại mỗi lần chạy)
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/maap_test
python -m pytest -v                                  # 67 test: QA-1..QA-6, FR3-FR5, RAG, R1-R6, LLM adapters
python scripts/check_architecture.py                 # kiểm tra quy tắc phụ thuộc R2-R6 trong code
python scripts/qa_benchmark.py --seed-bulk 3400      # thêm ~10.000 step_runs rồi đo QA-3/QA-5
```

| Kịch bản | Cách kiểm chứng | Kết quả đo |
|---|---|---|
| QA-1 Reliability | Gây lỗi LLM: đúng 1 retry tự động, lỗi lưu `error_message`, bước đã xong được giữ | test đạt |
| QA-2 Security | Mọi API nghiệp vụ không có token trả 401; sai vai trò trả 403; mật khẩu được băm | test đạt (≥ 30 endpoint) |
| QA-3 Performance | Bắt đầu workflow trả `202 + run_id` khi LLM chậm 1,5 s/bước | ~27 ms (mục tiêu ≤ 3 s) |
| QA-4 Recoverability | Retry thủ công chỉ chạy lại bước lỗi từ `input_context` đã lưu; retry đồng thời trả 409 | test đạt |
| QA-5 Performance | History/Dashboard trên 10.200 step_runs, trang ≤ 50 | ~10 ms / ~26 ms (mục tiêu ≤ 2 s) |
| QA-6 Auditability | Tạo/sửa/xoá/chạy/retry/duyệt đều có `activity_logs` (ai, làm gì, đối tượng, lúc nào) | test đạt |
| R01 Restart | `docker compose restart app` khi bước đang chạy: bước bị đánh dấu `interrupted`, retry được | đã thử thật |

Kịch bản demo từng bước nằm ở menu **Demo QA** (tài khoản Admin).

## 4. Ánh xạ code ↔ kiến trúc

| Thành phần kiến trúc (C&C / Module view) | Code |
|---|---|
| React Web App | `frontend/src` |
| API Routers (thin) | `backend/app/api/routes/*` |
| Auth & RBAC | `backend/app/api/deps.py` (`get_actor`), `app/services/auth_service.py`, `app/core/security.py` |
| User / Agent / Workflow / Task Service | `backend/app/services/*_service.py` |
| Workflow Coordinator + StepExecutor (C4 L4) | `app/services/coordinator.py`, `app/services/step_executors.py` |
| LLM Client (Gemini, OpenAI-compatible, Mock, FaultInjecting) | `app/integrations/llm_client.py`, `scripts/check_llm_connection.py` |
| Knowledge Service (RAG, BM25) | `app/services/knowledge/*`, `app/integrations/document_parser.py` |
| History & Monitoring | `app/services/history_service.py` |
| Activity Log Service | `app/services/activity_log_service.py` |
| Notification Adapter | `app/integrations/notification_adapter.py` |
| Repository / ORM | `app/repositories/repos.py`, `app/models/entities.py` |
| Allocation view | `Dockerfile`, `docker-compose.yml` |

## 5. Cấu trúc thư mục

```
backend/   FastAPI (app/api, app/services, app/integrations, app/repositories, app/models), tests/, scripts/
frontend/  React + Vite SPA
database/  schema.sql (DDL PostgreSQL để tham khảo / DBeaver)
docs/      Architecture Design Document v1.5 (v1.3 giữ để so sánh)
```
