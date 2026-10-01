"""Mostra as notas de similaridade do acervo para calibrar o corte de relevância.

Uso: python -m tests.calibrar_busca <job_id>   (o job precisa ter indexado exemplo/acervo)
"""
import sys
from pathlib import Path

from app.ingest import extract_chunks
from app.ollama_client import embed
from app.retrieve import search

QUERIES = [
    "gerenciamento de relacionamento com o cliente CRM",
    "backlog do produto e histórias de usuário",
    "heurísticas de usabilidade e wireframe",
    "controle de acesso baseado em papéis",
    "política de backup e recuperação",
    "trilha de auditoria e registro de logs",
    "VPN IPsec site-to-site entre unidades",
    "RAID tolerância a falhas de disco",
]

job_id = sys.argv[1]
chunks = extract_chunks(sorted((Path(__file__).resolve().parents[1] / "exemplo" / "acervo").glob("*.pdf")))
for query, vector in zip(QUERIES, embed(QUERIES)):
    hits = search(job_id, chunks, query, vector, k=4)
    print(f"\n{query}")
    for chunk, score in hits:
        print(f"  {score:.3f}  {chunk.author:<22} {chunk.text[:70]!r}")
