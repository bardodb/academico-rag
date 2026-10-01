from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config import QDRANT_URL
from app.ingest import Chunk
from app.ollama_client import embed


def collection_name(job_id: str) -> str:
    return f"acad_{job_id}"


def client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL, timeout=30)


def index_chunks(job_id: str, chunks: list[Chunk]) -> str:
    vectors = embed([chunk.text for chunk in chunks])
    if len(vectors) != len(chunks):
        raise RuntimeError("A quantidade de embeddings não corresponde aos trechos.")
    name = collection_name(job_id)
    qdrant = client()
    if qdrant.collection_exists(name):
        qdrant.delete_collection(name)
    qdrant.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=len(vectors[0]), distance=Distance.COSINE),
    )
    points = [
        PointStruct(id=index, vector=vectors[index], payload=chunks[index].to_payload())
        for index in range(len(chunks))
    ]
    qdrant.upsert(collection_name=name, points=points)
    return name


def qdrant_ready() -> bool:
    try:
        client().get_collections()
        return True
    except Exception:
        return False
