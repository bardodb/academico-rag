import re

from rank_bm25 import BM25Okapi

from app.config import DENSE_MIN, STRONG_DENSE, TOP_K
from app.ingest import Chunk
from app.store import client, collection_name

TOKEN = re.compile(r"[a-z0-9à-ÿ]+", re.IGNORECASE)
STOPWORDS = {
    "para", "como", "mais", "menos", "sobre", "entre", "depois", "antes",
    "também", "tambem", "pelo", "pela", "pelos", "pelas", "este", "esta",
    "esse", "essa", "isso", "aquele", "aquela", "quando", "onde", "porque",
    "pois", "desde", "ainda", "muito", "muitos", "muita", "muitas", "cada",
    "todo", "toda", "todos", "todas", "não", "nao", "sim", "com", "sem",
    "uma", "uns", "umas", "que", "dos", "das", "nos", "nas", "por", "seu",
    "sua", "seus", "suas", "foi", "são", "sao", "ser", "ter", "tem", "há",
    "the", "and", "deve", "devem", "informe", "apresente", "descreva",
    "inclua", "trabalho", "seção", "secao", "texto",
}


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def content_terms(text: str) -> set[str]:
    return {token for token in tokenize(text) if len(token) >= 5 and token not in STOPWORDS}


def search(job_id: str, chunks: list[Chunk], query: str, query_vector: list[float], k: int = TOP_K) -> list[tuple[Chunk, float]]:
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    dense_ranked, dense_scores = _dense(job_id, query_vector)
    lexical_ranked = _bm25(chunks, query)
    fused = _rrf([dense_ranked, lexical_ranked])
    allowed = set(dense_ranked) | set(lexical_ranked)
    hits: list[tuple[Chunk, float]] = []
    for chunk_id in fused:
        if chunk_id not in allowed or chunk_id not in by_id:
            continue
        hits.append((by_id[chunk_id], dense_scores.get(chunk_id, 0.0)))
        if len(hits) >= k:
            break
    return hits


def has_support(query: str, hits: list[tuple[Chunk, float]]) -> bool:
    if not hits:
        return False
    terms = content_terms(query)
    for chunk, score in hits[:5]:
        if score >= STRONG_DENSE:
            return True
        if terms and terms & content_terms(chunk.text):
            return True
    return False


def _dense(job_id: str, query_vector: list[float]) -> tuple[list[str], dict[str, float]]:
    qdrant = client()
    name = collection_name(job_id)
    if hasattr(qdrant, "query_points"):
        result = qdrant.query_points(
            collection_name=name,
            query=query_vector,
            limit=10,
            with_payload=True,
        )
        points = result.points
    else:
        points = qdrant.search(
            collection_name=name,
            query_vector=query_vector,
            limit=10,
            with_payload=True,
        )
    ranked: list[str] = []
    scores: dict[str, float] = {}
    for point in points:
        payload = point.payload or {}
        chunk_id = str(payload.get("chunk_id", ""))
        if not chunk_id:
            continue
        score = float(point.score)
        scores[chunk_id] = score
        if score >= DENSE_MIN:
            ranked.append(chunk_id)
    return ranked, scores


def _bm25(chunks: list[Chunk], query: str, limit: int = 10) -> list[str]:
    if not chunks:
        return []
    corpus = [tokenize(chunk.text) or ["vazio"] for chunk in chunks]
    engine = BM25Okapi(corpus)
    scores = engine.get_scores(tokenize(query))
    order = sorted(range(len(scores)), key=lambda index: float(scores[index]), reverse=True)
    ranked: list[str] = []
    for index in order:
        if float(scores[index]) <= 0:
            break
        ranked.append(chunks[index].chunk_id)
        if len(ranked) >= limit:
            break
    return ranked


def _rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (k + position)
    return sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
