"""Chunking + TF-IDF retrieval. (Tiny enough to ship; swappable for a real
embedding model behind an env flag.)"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class Chunk:
    chunk_id: str
    source: str
    text: str


@dataclass
class Hit:
    chunk: Chunk
    score: float


def chunk_text(text: str, source: str, max_chars: int = 600) -> list[Chunk]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[Chunk] = []
    buffer: list[str] = []
    length = 0
    for para in paragraphs:
        if length + len(para) > max_chars and buffer:
            chunks.append(Chunk(
                chunk_id=f"{source}#{len(chunks) + 1}",
                source=source,
                text="\n\n".join(buffer),
            ))
            buffer, length = [], 0
        buffer.append(para)
        length += len(para)
    if buffer:
        chunks.append(Chunk(
            chunk_id=f"{source}#{len(chunks) + 1}",
            source=source,
            text="\n\n".join(buffer),
        ))
    return chunks


class CitationIndex:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        corpus = [c.text for c in chunks]
        self.vectoriser = TfidfVectorizer(stop_words="english", max_features=4000)
        if corpus:
            self.matrix = self.vectoriser.fit_transform(corpus)
        else:
            self.matrix = None

    def query(self, question: str, top_k: int) -> list[Hit]:
        if self.matrix is None or not self.chunks:
            return []
        question_vec = self.vectoriser.transform([question])
        scores = cosine_similarity(question_vec, self.matrix)[0]
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [Hit(chunk=self.chunks[i], score=float(scores[i])) for i in top_indices if scores[i] > 0]
