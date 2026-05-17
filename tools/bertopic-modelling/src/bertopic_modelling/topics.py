"""BERTopic wrapper that returns a structured result. Falls back to TF-IDF + KMeans
if BERTopic / sentence-transformers fail to import (e.g. in CI without ML wheels)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer


def _try_bertopic_imports():  # lazy: importing sentence-transformers at module load adds 8+ s
    try:
        from bertopic import BERTopic
        from sentence_transformers import SentenceTransformer
        from umap import UMAP
        return BERTopic, SentenceTransformer, UMAP
    except Exception:  # pragma: no cover — fallback path
        return None


@dataclass
class TopicResult:
    topic_per_document: list[int]
    top_words_per_topic: dict[int, list[str]]
    embedding_2d: np.ndarray


def _fallback(documents: list[str], num_topics: int) -> TopicResult:
    n_clusters = max(2, num_topics or 6)
    vectoriser = TfidfVectorizer(max_features=2000, stop_words="english")
    matrix = vectoriser.fit_transform(documents)
    kmeans = KMeans(n_clusters=min(n_clusters, max(2, matrix.shape[0] - 1)), n_init=10, random_state=42)
    labels = kmeans.fit_predict(matrix)
    vocab = np.array(vectoriser.get_feature_names_out())
    top_words: dict[int, list[str]] = {}
    for cluster in range(kmeans.n_clusters):
        centre = kmeans.cluster_centers_[cluster]
        indices = np.argsort(centre)[::-1][:8]
        top_words[cluster] = vocab[indices].tolist()
    components = min(2, matrix.shape[1] - 1, matrix.shape[0] - 1)
    embedding = TruncatedSVD(n_components=max(components, 2), random_state=42).fit_transform(matrix)
    if embedding.shape[1] == 1:
        embedding = np.hstack([embedding, np.zeros((embedding.shape[0], 1))])
    return TopicResult(
        topic_per_document=labels.tolist(),
        top_words_per_topic=top_words,
        embedding_2d=embedding[:, :2],
    )


def fit(documents: list[str], num_topics: int) -> TopicResult:
    imports = _try_bertopic_imports() if len(documents) >= 8 else None
    if imports is None:
        return _fallback(documents, num_topics)
    BERTopic, SentenceTransformer, UMAP = imports
    encoder = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = encoder.encode(documents, show_progress_bar=False)
    nr_topics = num_topics if num_topics > 0 else "auto"
    model = BERTopic(nr_topics=nr_topics, verbose=False, calculate_probabilities=False)
    topics, _ = model.fit_transform(documents, embeddings)
    top_words: dict[int, list[str]] = {}
    for topic_id, _ in model.get_topics().items():
        words = [w for w, _ in model.get_topic(topic_id) or []][:8]
        top_words[int(topic_id)] = words
    reducer = UMAP(n_components=2, random_state=42, n_neighbors=min(15, max(2, len(documents) - 1)))
    embedding_2d = reducer.fit_transform(embeddings)
    return TopicResult(
        topic_per_document=[int(t) for t in topics],
        top_words_per_topic=top_words,
        embedding_2d=embedding_2d,
    )
