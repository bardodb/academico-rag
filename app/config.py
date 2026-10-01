import os
from pathlib import Path

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
EMBED_MODEL = "bge-m3"
CHAT_MODEL = "qwen2.5:7b"
DATA_ROOT = Path(os.environ.get("ACADEMICO_RAG_DATA", Path.home() / ".local" / "academico-rag"))
JOBS_DIR = DATA_ROOT / "jobs"
STATIC_DIR = Path(__file__).resolve().parent / "static"

TARGET_CHARS = 800
MAX_CHARS = 900
TOP_K = 4
DENSE_MIN = 0.30
STRONG_DENSE = 0.55
# Calibrado com tests/calibrar_busca.py (bge-m3): trechos pertinentes >= 0,55; alheios <= 0,50.
EVIDENCE_MIN = 0.54
# 8k cabe na GTX 1660 (6 GB) com o qwen2.5:7b Q4 sem transbordar para a CPU.
NUM_CTX = 8192
CHAT_TIMEOUT = 600.0

MAX_TASKS = 8
QUERIES_PER_TASK = 4
CHUNKS_PER_TASK = 8
CASE_CHARS = 6000
BRIEF_FALLBACK_CHARS = 14000
NORMS_CHARS = 2000
TASK_NORMS_CHARS = 3000
