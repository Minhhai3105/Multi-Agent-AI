"""Extract plain text from uploaded knowledge documents (.txt, .md, .pdf, .docx)."""
from __future__ import annotations

import io

from docx import Document as DocxDocument
from pypdf import PdfReader
from pypdf.errors import PdfReadError

SUPPORTED_EXTENSIONS = (".txt", ".md", ".pdf", ".docx")


class DocumentParseError(Exception):
    pass


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith((".txt", ".md")):
        for encoding in ("utf-8-sig", "utf-16", "cp1258", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise DocumentParseError("Không đọc được bảng mã của file văn bản")
    if name.endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except (PdfReadError, ValueError) as exc:
            raise DocumentParseError("File PDF bị lỗi hoặc được mã hoá") from exc
    if name.endswith(".docx"):
        try:
            doc = DocxDocument(io.BytesIO(data))
        except Exception as exc:  # python-docx raises several unrelated types
            raise DocumentParseError("File DOCX bị lỗi") from exc
        lines = []
        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            lines.append(f"# {text}" if style.startswith("heading") else text)
        for table in doc.tables:
            for row in table.rows:
                lines.append(" | ".join(cell.text.strip() for cell in row.cells))
        return "\n\n".join(lines)
    raise DocumentParseError(
        "Định dạng không hỗ trợ. Chỉ nhận: " + ", ".join(SUPPORTED_EXTENSIONS)
    )
