"""Mostra a resposta crua do filtro de relevância para as tarefas do caso CAMC.

Uso: python -m tests.depurar_relevancia <job_id>   (o job precisa ter indexado exemplo/acervo)
"""
import sys
from pathlib import Path

from app.brief import parse_brief, pdf_text, split_norms
from app.config import CHAT_MODEL, EMBED_MODEL, EVIDENCE_MIN, TASK_NORMS_CHARS
from app.generate import _dedupe, _queries, _relevant
from app.ingest import extract_chunks
from app.ollama_client import embed, unload
from app.retrieve import search

ROOT = Path(__file__).resolve().parents[1]
job_id = sys.argv[1]
brief = parse_brief(pdf_text(next(ROOT.parent.glob("PROJETO_INTEGRADO*.pdf"))))
chunks = extract_chunks(sorted((ROOT / "exemplo" / "acervo").glob("*.pdf")))
queries = {task.number: _queries(task) for task in brief.tasks}
unload(CHAT_MODEL)
flat = [(n, q) for n, qs in queries.items() for q in qs]
found = {task.number: [] for task in brief.tasks}
for (number, query), vector in zip(flat, embed([q for _n, q in flat])):
    hits = search(job_id, chunks, query, vector)
    found[number].extend(c for c, s in hits if s >= EVIDENCE_MIN)
found = {n: _dedupe(cs, 8) for n, cs in found.items()}
unload(EMBED_MODEL)
_general, guides = split_norms((ROOT / "exemplo" / "normas_camc.md").read_text(encoding="utf-8"))
for task in brief.tasks:
    kept = _relevant(task, found[task.number], guides.get(task.number, "")[:TASK_NORMS_CHARS])
    print(f"\n{task.heading}")
    print("  candidatos:", [f"{c.chunk_id} {c.author}" for c in found[task.number]])
    print("  mantidos:  ", [f"{c.chunk_id} {c.author}" for c in kept])
