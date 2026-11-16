"""Chunking and BM25 retrieval for the knowledge base (RAG extension).

Chosen so that RAG runs on a normal laptop without GPU, extra services or API quota
(constraints C6, C7). The Retriever is a small interface: an embedding-based
retriever can replace BM25 later without touching the step executor (extension point).
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

_HEADING_RE = re.compile(
    r"^\s*(#{1,6}\s+.+|(chương|điều|mục|phần)\s+[0-9ivxlc]+[\.:]?.*)$", re.IGNORECASE
)
_STOPWORDS = {
    "la", "va", "cua", "cac", "co", "duoc", "cho", "trong", "voi", "nhung", "mot", "nay",
    "khi", "thi", "de", "theo", "ve", "tu", "den", "nhu", "hoac", "tai", "do", "o", "se",
    "da", "the", "nao", "gi", "bao", "toi", "ban", "minh", "a", "nhe", "khong",
}


def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


def tokenize(text: str) -> list[str]:
    """Lower-case, accent-insensitive unigrams plus bigrams (bigrams restore some of the
    precision lost by removing Vietnamese diacritics, e.g. 'nghi phep')."""
    words = re.findall(r"\w+", strip_accents(text.lower()))
    words = [w for w in words if w not in _STOPWORDS and len(w) > 0]
    bigrams = [f"{a}_{b}" for a, b in zip(words, words[1:])]
    return words + bigrams


@dataclass
class Chunk:
    index: int
    heading: str
    content: str


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[Chunk]:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n")
    paragraphs: list[tuple[str, str]] = []  # (heading, paragraph)
    heading = ""
    buffer: list[str] = []

    def flush_paragraph() -> None:
        if buffer:
            paragraphs.append((heading, " ".join(buffer).strip()))
            buffer.clear()

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            flush_paragraph()
            continue
        if _HEADING_RE.match(line) and len(line) < 160:
            flush_paragraph()
            heading = line.lstrip("#").strip()
            paragraphs.append((heading, f"__HEADING__{heading}"))
            continue
        buffer.append(line)
    flush_paragraph()

    chunks: list[Chunk] = []
    current: list[str] = []
    current_heading = ""

    def emit() -> None:
        body = "\n".join(p for p in current if p).strip()
        if body:
            chunks.append(Chunk(index=len(chunks), heading=current_heading[:250], content=body))

    for para_heading, para in paragraphs:
        if para.startswith("__HEADING__"):
            emit()
            current = []
            current_heading = para_heading
            continue
        pieces = [para] if len(para) <= size else _split_long(para, size)
        for piece in pieces:
            if current and sum(len(p) for p in current) + len(piece) > size:
                emit()
                tail = current[-1][-overlap:] if overlap and current else ""
                current = [tail] if tail else []
            current.append(piece)
            current_heading = current_heading or para_heading
    emit()
    return chunks


def _split_long(paragraph: str, size: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?;])\s+", paragraph)
    out, buf = [], ""
    for s in sentences:
        if len(buf) + len(s) + 1 > size and buf:
            out.append(buf.strip())
            buf = ""
        buf += " " + s
    if buf.strip():
        out.append(buf.strip())
    return out


@dataclass
class IndexedChunk:
    chunk_id: int
    document_title: str
    chunk_index: int
    heading: str
    content: str


@dataclass
class Hit:
    chunk: IndexedChunk
    score: float


class BM25Index:
    def __init__(self, chunks: list[IndexedChunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.doc_tokens = [Counter(tokenize(f"{c.heading} {c.content}")) for c in chunks]
        self.doc_len = [sum(t.values()) for t in self.doc_tokens]
        self.avg_len = (sum(self.doc_len) / len(self.doc_len)) if chunks else 0.0
        df: Counter = Counter()
        for tokens in self.doc_tokens:
            df.update(tokens.keys())
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, top_k: int = 4) -> list[Hit]:
        terms = tokenize(query)
        if not terms or not self.chunks:
            return []
        scores = []
        for i, tokens in enumerate(self.doc_tokens):
            score = 0.0
            for term in terms:
                tf = tokens.get(term)
                if not tf:
                    continue
                norm = tf * (self.k1 + 1) / (
                    tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / (self.avg_len or 1))
                )
                score += self.idf.get(term, 0.0) * norm
            if score > 0:
                scores.append((score, i))
        scores.sort(reverse=True)
        return [Hit(chunk=self.chunks[i], score=round(s, 3)) for s, i in scores[:top_k]]
