import logging
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.brief import parse_brief, pdf_text
from app.config import CHAT_MODEL, EMBED_MODEL, JOBS_DIR, STATIC_DIR
from app.docx_writer import save_docx
from app.generate import write_paper
from app.ingest import extract_chunks
from app.ollama_client import OllamaError, list_models
from app.store import index_chunks, qdrant_ready

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("academico")

app = FastAPI(title="RAG acadêmico local")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

jobs: dict[str, dict] = {}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    ollama_ok = False
    models: list[str] = []
    try:
        models = list_models()
        ollama_ok = True
    except httpx.HTTPError:
        ollama_ok = False
    return {
        "ollama": ollama_ok,
        "qdrant": qdrant_ready(),
        "chat_model": _model_present(models, CHAT_MODEL),
        "embed_model": _model_present(models, EMBED_MODEL),
    }


@app.post("/api/jobs")
async def create_job(
    background: BackgroundTasks,
    theme: str = Form(...),
    norms: str = Form(""),
    brief_text: str = Form(""),
    brief: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
) -> dict:
    theme = theme.strip()
    if not theme:
        raise HTTPException(status_code=400, detail="Informe o tema.")

    job_id = uuid4().hex
    job_dir = JOBS_DIR / job_id
    source_dir = job_dir / "acervo"
    source_dir.mkdir(parents=True, exist_ok=True)

    brief_path = None
    if brief is not None and brief.filename:
        brief_path = await _save_pdf(brief, job_dir)
    if brief_path is None and not brief_text.strip():
        raise HTTPException(status_code=400, detail="Envie o PDF do enunciado ou cole o enunciado em texto.")

    sources = [await _save_pdf(upload, source_dir) for upload in files or [] if upload.filename]

    jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "detail": "Na fila",
        "sections_total": 0,
        "sections_done": 0,
        "gaps": [],
        "preview": "",
        "title": theme,
        "error": "",
    }
    background.add_task(_run_job, job_id, theme, norms.strip(), brief_path, brief_text.strip(), sources)
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabalho não encontrado.")
    return job


@app.get("/api/jobs/{job_id}/trabalho.md")
def download_markdown(job_id: str) -> FileResponse:
    return _download(job_id, "trabalho.md", "text/markdown; charset=utf-8")


@app.get("/api/jobs/{job_id}/trabalho.docx")
def download_docx(job_id: str) -> FileResponse:
    return _download(
        job_id,
        "trabalho.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def _run_job(job_id: str, theme: str, norms: str, brief_path: Path | None, brief_text: str,
             sources: list[Path]) -> None:
    def progress(**kwargs) -> None:
        jobs[job_id].update(kwargs)

    try:
        progress(status="extracting", detail="Lendo o enunciado e separando caso e tarefas")
        brief = parse_brief(pdf_text(brief_path) if brief_path else brief_text)
        chunks = []
        if sources:
            progress(status="extracting", detail="Lendo os PDFs do acervo")
            chunks = extract_chunks(sources)
            progress(status="indexing", detail=f"Indexando {len(chunks)} trechos do acervo")
            index_chunks(job_id, chunks)
        paper = write_paper(job_id, theme, norms, brief, chunks, progress)
        job_dir = JOBS_DIR / job_id
        (job_dir / "trabalho.md").write_text(paper.markdown, encoding="utf-8")
        save_docx(paper.markdown, job_dir / "trabalho.docx")
        preview = paper.markdown.split("## Relatório de lacunas")[0].removesuffix("---").strip()
        progress(status="done", detail="Trabalho pronto", gaps=paper.gaps, preview=preview,
                 title=paper.title, error="")
    except (OllamaError, ValueError, RuntimeError) as exc:
        log.exception("Falha no trabalho %s", job_id)
        progress(status="error", detail=str(exc), error=str(exc))
    except Exception as exc:
        log.exception("Falha inesperada no trabalho %s", job_id)
        progress(status="error", detail="Falha inesperada ao gerar o trabalho.", error=str(exc))


async def _save_pdf(upload: UploadFile, folder: Path) -> Path:
    filename = Path(upload.filename or "arquivo.pdf").name
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail=f"{filename} não é PDF.")
    content = await upload.read()
    if not content:
        raise HTTPException(status_code=400, detail=f"O arquivo {filename} está vazio.")
    dest = folder / filename
    dest.write_bytes(content)
    return dest


def _download(job_id: str, filename: str, media_type: str) -> FileResponse:
    path = JOBS_DIR / job_id / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="O arquivo ainda não está pronto.")
    return FileResponse(path, filename=filename, media_type=media_type)


def _model_present(models: list[str], expected: str) -> bool:
    return any(name == expected or name.startswith(f"{expected}:") for name in models)
