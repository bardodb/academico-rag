"""Teste ponta a ponta com o caso CAMC: enunciado separado do acervo citável.

Uso: com o servidor no ar (run.ps1), rode `python exemplo/rodar_job.py [caminho-do-enunciado.pdf]`.
"""
import os
import re
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from app.validate import _cut_loop  # noqa: E402

BASE = os.environ.get("RAG_URL", "http://127.0.0.1:8000")
ACERVO = sorted((HERE / "acervo").glob("*.pdf"))
THEME = "Modernização tecnológica integrada da CAMC (Cadeia Alimentar do Mel e Chia)"
NORMS = (HERE / "normas_camc.md").read_text(encoding="utf-8")


def _prose_lines(markdown: str) -> list[str]:
    lines, in_code = [], False
    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        elif not in_code:
            lines.append(line)
    return lines


def main() -> None:
    brief = Path(sys.argv[1]) if len(sys.argv) > 1 else next(HERE.parent.parent.glob("PROJETO_INTEGRADO*.pdf"))
    with httpx.Client(timeout=120) as client:
        health = client.get(f"{BASE}/api/health").json()
        print("HEALTH", health)
        files = [("brief", (brief.name, brief.read_bytes(), "application/pdf"))]
        files += [("files", (pdf.name, pdf.read_bytes(), "application/pdf")) for pdf in ACERVO]
        response = client.post(f"{BASE}/api/jobs", data={"theme": THEME, "norms": NORMS}, files=files)
        print("CREATE", response.status_code, response.text)
        response.raise_for_status()
        job_id = response.json()["id"]

        started, last, job = time.time(), "", {}
        while time.time() - started < 3600:
            job = client.get(f"{BASE}/api/jobs/{job_id}").json()
            line = f"{job['status']} {job.get('detail')} ({job.get('sections_done')}/{job.get('sections_total')})"
            if line != last:
                print(f"[{int(time.time() - started):>4}s] {line}", flush=True)
                last = line
            if job["status"] in {"done", "error"}:
                break
            time.sleep(5)
        if job.get("status") != "done":
            print("FAILED", job.get("error"))
            sys.exit(1)

        markdown = client.get(f"{BASE}/api/jobs/{job_id}/trabalho.md").text
        docx = client.get(f"{BASE}/api/jobs/{job_id}/trabalho.docx").content
        out = HERE / "saida_camc"
        out.mkdir(exist_ok=True)
        (out / "trabalho.md").write_text(markdown, encoding="utf-8")
        (out / "trabalho.docx").write_bytes(docx)

    body = markdown.split("## Relatório de lacunas")[0]
    refs = body.split("## REFERÊNCIAS")[-1]
    checks = {
        "5 passos no desenvolvimento": len(re.findall(r"^### 2\.\d+ Passo \d", body, re.M)) == 5,
        "sem frases institucionais": not re.search(r"prezad|bem-vind|bons estudos", body, re.I),
        "enunciado não citado": "PROJETO_INTEGRADO" not in body and "enunciado" not in refs.lower(),
        "sem corte de 4000": "cortadas" not in markdown,
        "cercas de código balanceadas": body.count("```") % 2 == 0,
        "sem citação duplicada": not re.search(r"(\([A-Z][^()]*\d{4}\)) e \1", body),
        "orientações seguidas (RBAC e RAID)": "Operador de Campo" in body and "RAID 10" in body,
        "citações do acervo": len(re.findall(r"\([A-Z][A-Z;. ]+(?:et al\.)?, \d{4}\)|[A-Z][a-z]+(?: et al\.)? \(\d{4}\)",
                                             body)) >= 3,
        "sem troca de idioma": not re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", body),
        "sem laço de repetição": not re.search(r"^(.+)\n(?:\1\n){3,}", body, re.M)
                                 and not any(_cut_loop(line)[1] for line in _prose_lines(body)),
        "tabelas sem linhas truncadas": not any(line.startswith("|") and not line.rstrip().endswith("|")
                                                for line in _prose_lines(body)),
        "sem marcadores [cN] residuais": not re.search(r"\[\s*c\d+", body),
        "referências do acervo": sum(1 for line in refs.splitlines() if line.startswith("- ")) >= 2,
        "docx válido": docx.startswith(b"PK"),
    }
    for name, ok in checks.items():
        print("OK  " if ok else "FALHA", name)
    print("Caracteres do trabalho:", len(body), "| saída em", out)
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
