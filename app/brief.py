"""Separa o estudo de caso e as tarefas do enunciado."""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.config import BRIEF_FALLBACK_CHARS, CASE_CHARS, MAX_TASKS
from app.ollama_client import chat

TASK_HEADER = re.compile(
    r"^[ \t]*(passo|etapa|tarefa|atividade|parte|quest[ãa]o)[ \t]*(\d{1,2})[ \t]*[:.\-–—)][ \t]*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
STOP_HEADER = re.compile(
    r"^[ \t]*(?:NORMAS\b|CRIT[ÉE]RIOS\b|ORIENTA[ÇC][ÕO]ES PARA\b|REFER[ÊE]NCIAS\b|BIBLIOGRAFIA\b|CRONOGRAMA\b)",
    re.MULTILINE,
)
DELIVERABLES = re.compile(r"^[ \t]*(?:o que (?:deve|devem) (?:ser )?entregar|entreg[áa]ve(?:l|is)|entregas?)\b.*$",
                          re.IGNORECASE | re.MULTILINE)
NORMS_TASK_HEADER = re.compile(
    r"^[ \t>*#\-]*\**[ \t]*(?:passo|etapa|tarefa|atividade|parte|quest[ãa]o)[ \t]*(\d{1,2})\b",
    re.IGNORECASE | re.MULTILINE,
)
MARKDOWN_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]", re.MULTILINE)
CONTEXT_MARKER = re.compile(r"^[ \t]*(?:contexto|estudo de caso|situa[çc][ãa]o[- ]problema|cen[áa]rio)\b",
                            re.IGNORECASE | re.MULTILINE)
PRE_TASK_NOISE = re.compile(r"^[ \t]*(?:ATIVIDADE A SER REALIZADA|DESAFIO\b.*)$", re.IGNORECASE | re.MULTILINE)

CASE_SYSTEM = (
    "Você extrai o estudo de caso de um enunciado acadêmico. "
    "Liste somente fatos sobre a organização descrita: nome, ramo, produtos, processos, "
    "sistemas atuais, problemas e objetivos. Ignore boas-vindas, objetivos de aprendizagem, "
    "orientações ao aluno, notas, prazos e critérios de correção. "
    "Responda em português, uma lista com '- ' no início de cada fato, sem comentários."
)

TASKS_SYSTEM = (
    "Você extrai as tarefas que um enunciado acadêmico pede para resolver. "
    "Responda somente JSON no formato "
    '{"tasks":[{"title":"...","statement":"...","deliverables":["..."]}]}. '
    "Ignore boas-vindas, normas de formatação e critérios de correção."
)


@dataclass
class Task:
    number: int
    title: str
    statement: str
    deliverables: list[str] = field(default_factory=list)
    label: str = ""

    @property
    def heading(self) -> str:
        return f"{self.label or f'Tarefa {self.number}'}: {self.title}"


@dataclass
class Brief:
    case_facts: str
    tasks: list[Task]
    gaps: list[str] = field(default_factory=list)


def pdf_text(path: Path) -> str:
    document = pymupdf.open(path)
    try:
        return "\n".join(page.get_text("text") for page in document)
    finally:
        document.close()


def parse_brief(text: str) -> Brief:
    text = _clean(text)
    gaps: list[str] = []
    tasks, first_task_at = _tasks_by_headers(text)
    if not tasks:
        tasks = _tasks_by_model(text)
        first_task_at = len(text)
        if tasks:
            gaps.append("As tarefas não tinham cabeçalhos como “Passo 1:”; foram extraídas pelo modelo.")
    if not tasks:
        raise ValueError("Não encontrei tarefas no enunciado (ex.: “Passo 1: ...”).")
    case_facts = _case_facts(text[:first_task_at])
    if not case_facts:
        gaps.append("Não foi possível extrair fatos do estudo de caso do enunciado.")
    return Brief(case_facts=case_facts, tasks=tasks[:MAX_TASKS], gaps=gaps)


def split_norms(norms: str) -> tuple[str, dict[int, str]]:
    """Separa as orientações por tarefa ("PASSO 1: ...") das orientações gerais."""
    matches = list(NORMS_TASK_HEADER.finditer(norms))
    per_task: dict[int, str] = {}
    general = norms
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(norms)
        heading = MARKDOWN_HEADING.search(norms, match.end(), end)
        if heading:
            end = heading.start()
        section = norms[match.start():end]
        per_task[int(match.group(1))] = section.strip()
        general = general.replace(section, "\n")
    return re.sub(r"\n{3,}", "\n\n", general).strip(), per_task


def _clean(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(\w) -(\w)", r"\1-\2", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _tasks_by_headers(text: str) -> tuple[list[Task], int]:
    matches = list(TASK_HEADER.finditer(text))
    if not matches:
        return [], len(text)
    tasks: list[Task] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        stop = STOP_HEADER.search(text, match.end(), end)
        if stop:
            end = stop.start()
        body = text[match.end():end].strip()
        statement, deliverables = _split_deliverables(body)
        number = int(match.group(2))
        label = f"{match.group(1).capitalize()} {number}"
        title = match.group(3).strip() or label
        tasks.append(Task(number, _title_case(title), _join_lines(statement), deliverables, label))
    return tasks, matches[0].start()


def _split_deliverables(body: str) -> tuple[str, list[str]]:
    marker = DELIVERABLES.search(body)
    if not marker:
        return body, []
    items = []
    for line in body[marker.end():].splitlines():
        line = line.strip()
        if re.match(r"^[-•*]\s*", line):
            items.append(re.sub(r"^[-•*]\s*", "", line))
        elif items and line:
            items[-1] = f"{items[-1]} {line}"
    return body[:marker.start()], items


def _tasks_by_model(text: str) -> list[Task]:
    messages = [
        {"role": "system", "content": TASKS_SYSTEM},
        {"role": "user", "content": text[:BRIEF_FALLBACK_CHARS]},
    ]
    try:
        raw = chat(messages, json_mode=True, temperature=0.1, num_predict=1500)
        data = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return []
    tasks = []
    for number, item in enumerate(data.get("tasks") or [], start=1):
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            continue
        tasks.append(Task(
            number,
            str(item["title"]).strip(),
            str(item.get("statement") or "").strip(),
            [str(d).strip() for d in item.get("deliverables") or [] if str(d).strip()],
        ))
    return tasks


def _case_facts(pre_task: str) -> str:
    marker = CONTEXT_MARKER.search(pre_task)
    region = pre_task[marker.start():] if marker else pre_task
    region = PRE_TASK_NOISE.sub("", region).strip()[:CASE_CHARS]
    if not region:
        return ""
    facts = chat(
        [{"role": "system", "content": CASE_SYSTEM}, {"role": "user", "content": region}],
        temperature=0.1,
        num_predict=900,
    )
    lines = [line.strip() for line in facts.splitlines() if line.strip().startswith(("-", "•", "*"))]
    return "\n".join("- " + re.sub(r"^[-•*]\s*", "", line) for line in lines)


def _join_lines(text: str) -> str:
    paragraphs = re.split(r"\n\s*\n", text.strip())
    return "\n".join(re.sub(r"\s*\n\s*", " ", p).strip() for p in paragraphs if p.strip())


def _title_case(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip(" :.-")
    if title.isupper():
        small = {"de", "da", "do", "das", "dos", "e", "a", "o", "em", "para", "com"}
        words = title.lower().split()
        return " ".join(w if i and w in small else w.capitalize() for i, w in enumerate(words))
    return title
