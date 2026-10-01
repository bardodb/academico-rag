import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.brief import Brief, Task, split_norms
from app.config import (CHAT_MODEL, CHUNKS_PER_TASK, EMBED_MODEL, EVIDENCE_MIN, NORMS_CHARS, QUERIES_PER_TASK,
                        TASK_NORMS_CHARS, TOP_K)
from app.ingest import Chunk
from app.ollama_client import chat, embed, unload
from app.retrieve import search
from app.validate import CITE, FOREIGN_SCRIPT, bibliography, clean_markdown

Progress = Callable[..., None]

ROLE = (
    "Você é engenheiro de software e analista de sistemas sênior e redige, em português do Brasil, "
    "um trabalho acadêmico técnico. Tom técnico-acadêmico e impessoal, frases completas. "
)
RULES = (
    "Regras obrigatórias: "
    "1) Nunca escreva nomes de autores, anos ou referências por conta própria. "
    "2) Quando usar uma ideia de um trecho numerado, termine a frase com o identificador dele, por exemplo [c3]. "
    "3) Use somente identificadores que aparecem nos trechos fornecidos. "
    "4) Frases de conhecimento técnico geral podem ficar sem identificador. "
    "5) O enunciado apenas descreve a tarefa: não o cite, não copie suas frases e não se dirija ao leitor nem ao aluno."
)
QUERIES_SYSTEM = (
    "Você gera consultas de busca para achar a fundamentação teórica de uma tarefa técnica em livros, "
    "artigos e normas da área de computação. Responda somente JSON no formato "
    '{"queries":["..."]}. '
    f"Gere até {QUERIES_PER_TASK} consultas curtas, cada uma com um conceito técnico "
    "(ex.: \"controle de acesso baseado em papéis\"). Não use o nome da empresa."
)
SOLUTION_FORMAT = (
    "Formato Markdown: subtítulos com '### ', listas com '- ', tabelas Markdown (linhas com '|') para "
    "comparar ou especificar itens, e blocos ``` para diagramas e esboços em texto. "
    "Não escreva título principal, conclusão nem autoavaliação."
)
DELIVERABLE_NOISE = re.compile(r"conclus[ãa]o da atividade|autoavalia[çc][ãa]o", re.IGNORECASE)


@dataclass
class Paper:
    title: str
    markdown: str
    gaps: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)


def write_paper(job_id: str, theme: str, norms: str, brief: Brief, chunks: list[Chunk], progress: Progress) -> Paper:
    tasks = brief.tasks
    gaps = list(brief.gaps)
    general, guides = split_norms(norms)
    general = general[:NORMS_CHARS]
    guides = {number: text[:TASK_NORMS_CHARS] for number, text in guides.items()}
    total = len(tasks) + 2
    progress(status="planning", detail="Definindo a busca teórica de cada tarefa", sections_total=total, sections_done=0)

    evidence: dict[int, list[Chunk]] = {task.number: [] for task in tasks}
    if chunks:
        unload(EMBED_MODEL)
        queries = {task.number: _queries(task) for task in tasks}
        unload(CHAT_MODEL)
        progress(status="retrieving", detail="Buscando trechos no acervo")
        flat = [(number, q) for number, qs in queries.items() for q in qs]
        vectors = embed([q for _n, q in flat])
        for (number, query), vector in zip(flat, vectors):
            hits = search(job_id, chunks, query, vector)
            evidence[number].extend(chunk for chunk, score in hits if score >= EVIDENCE_MIN)
        for task in tasks:
            evidence[task.number] = _dedupe(evidence[task.number], CHUNKS_PER_TASK)
        unload(EMBED_MODEL)
        progress(status="retrieving", detail="Conferindo se os trechos tratam do assunto de cada tarefa")
        for task in tasks:
            before = len(evidence[task.number])
            evidence[task.number] = _relevant(task, evidence[task.number], guides.get(task.number, ""))
            if before and not evidence[task.number]:
                gaps.append(f"Os trechos achados para “{task.heading}” eram de outro assunto e foram descartados.")
            if not evidence[task.number]:
                gaps.append(f"Nenhum trecho do acervo sustentou a fundamentação de “{task.heading}”.")
    else:
        gaps.append("Nenhum PDF de acervo foi enviado: o texto não tem citações nem referências.")

    progress(status="writing", detail="Redigindo a introdução", sections_done=0)
    intro, intro_gaps, _ = clean_markdown(_intro(theme, brief, general), [], allow_citations=False)
    gaps.extend(intro_gaps)

    used: list[Chunk] = []
    sections: list[dict] = []
    for index, task in enumerate(tasks, start=1):
        progress(status="writing", detail=f"Redigindo {task.heading}", sections_done=index)
        found = evidence[task.number]
        guide = guides.get(task.number, "")
        theory, g1, u1 = clean_markdown(_theory(task, found, guide), found)
        solution, g2, u2 = clean_markdown(_solution(brief.case_facts, task, found[:TOP_K], guide, general), found)
        closing, g3, _ = clean_markdown(_closing(task, solution, guide), [], allow_citations=False)
        gaps.extend(g1 + g2 + g3)
        used.extend(u1 + u2)
        sections.append({"task": task, "theory": theory, "solution": solution, "closing": closing})

    progress(status="writing", detail="Redigindo a conclusão", sections_done=total - 1)
    conclusion, concl_gaps, _ = clean_markdown(_conclusion(theme, brief, sections, general), [],
                                               allow_citations=False)
    gaps.extend(concl_gaps)
    unload(CHAT_MODEL)

    references = bibliography(used)
    gaps = list(dict.fromkeys(gaps))
    markdown = assemble(theme, intro, sections, conclusion, references, gaps)
    progress(status="writing", detail="Formatando o documento", sections_done=total)
    return Paper(title=theme, markdown=markdown, gaps=gaps, references=references)


def _queries(task: Task) -> list[str]:
    messages = [
        {"role": "system", "content": QUERIES_SYSTEM},
        {"role": "user", "content": f"Tarefa: {task.title}\n{task.statement}"},
    ]
    try:
        data = json.loads(chat(messages, json_mode=True, temperature=0.1, num_predict=300))
        queries = [str(q).strip() for q in data.get("queries") or [] if str(q).strip()]
    except (ValueError, json.JSONDecodeError):
        queries = []
    return [task.title, *queries][: QUERIES_PER_TASK + 1]


RELEVANCE_SYSTEM = (
    "Você avalia se trechos de livros e normas (muitas vezes em inglês) servem de fundamentação teórica para "
    "uma tarefa técnica. Um trecho serve se explica, mesmo em parte, um conceito ou tecnologia que a tarefa "
    "usa (ex.: arquiteturas de VPN servem para interligar unidades). Não serve se é de outra área técnica, "
    "se só repete palavras soltas ou se é texto administrativo (avisos, sumário, isenções). "
    'Responda somente JSON no formato {"relevantes":["c1","c7"]}; use lista vazia se nenhum servir.'
)


def _relevant(task: Task, found: list[Chunk], guide: str) -> list[Chunk]:
    """A similaridade vetorial não separa assunto (ex.: guia de VPN aparece para usabilidade de app)."""
    if not found:
        return []
    excerpts = "\n\n".join(f"[{c.chunk_id}] {c.title or c.file}\n{c.text[:500]}" for c in found)
    topics = f"\nConceitos que a tarefa exige:\n{guide[:1500]}" if guide else ""
    messages = [
        {"role": "system", "content": RELEVANCE_SYSTEM},
        {"role": "user", "content": f"Tarefa: {task.title}\n{task.statement[:800]}{topics}\n\nTrechos:\n{excerpts}"},
    ]
    # O modelo nem sempre respeita a chave pedida ("relevant", "ids"...); vale qualquer identificador citado.
    keep = set(re.findall(r"c\d+", chat(messages, json_mode=True, temperature=0.0, num_predict=200)))
    return [chunk for chunk in found if chunk.chunk_id in keep]


def _theory(task: Task, found: list[Chunk], guide: str) -> str:
    if found:
        source = f"Trechos do acervo:\n{_excerpts(found)}"
    else:
        source = "Não há trechos do acervo: escreva conhecimento técnico consolidado, sem citar autores."
    cite = ("Apoie-se nos trechos do acervo que tratem do mesmo assunto e marque com o identificador [cN] "
            "cada frase sustentada por um deles; ignore trechos de outro assunto. " if found else "")
    user = (
        f"Tarefa: {task.title}\n{task.statement}\n\n{_guide_block(guide)}{source}\n\n"
        "Escreva a fundamentação teórica desta tarefa em 3 a 4 parágrafos, explicando os conceitos técnicos "
        "necessários para resolvê-la (se as orientações pedirem conceitos específicos, cubra-os). "
        f"{cite}Não fale da empresa ainda. Sem título e sem listas."
    )
    text = _ask(ROLE + RULES, user, 1100)
    if found and not CITE.search(text):
        retry = (
            f"Rascunho:\n{text}\n\nTrechos do acervo:\n{_excerpts(found)}\n\n"
            "O rascunho não usou os trechos. Reescreva-o mantendo o conteúdo e acrescente, ao fim de cada "
            "frase que um trecho realmente sustente, o identificador dele, como [c3]. Não cite trecho de "
            "outro assunto. Não invente autores nem anos. Sem título e sem listas."
        )
        text = _ask(ROLE + RULES, retry, 1100)
    return text


def _guide_block(guide: str) -> str:
    return f"Orientações específicas desta tarefa (siga item a item):\n{guide}\n\n" if guide else ""


def _solution(case_facts: str, task: Task, found: list[Chunk], guide: str, norms: str) -> str:
    deliverables = [d for d in task.deliverables if not DELIVERABLE_NOISE.search(d)]
    deliverables = [re.sub(r"^(?:print|captura de tela)\s+d[oa]s?\s+", "Representação em tabela do ", d, flags=re.I)
                    for d in deliverables]
    deliverables = [re.sub(r"^documento em pdf d[oa]s?\s+", "", d, flags=re.I) for d in deliverables]
    items = "\n".join(f"- {d}" for d in deliverables) or "- (não especificadas)"
    excerpts = f"\n\nTrechos do acervo (opcionais):\n{_excerpts(found)}" if found else ""
    form = f"\n\nNormas gerais do trabalho (não são fonte de fatos):\n{norms}" if norms and not guide else ""
    cover = ("Cubra cada item das orientações específicas e cada entrega exigida em subtítulos próprios. "
             if guide else "Cubra cada entrega exigida em um subtítulo próprio. ")
    user = (
        f"Estudo de caso (fatos da organização):\n{case_facts or '- (sem fatos extraídos)'}\n\n"
        f"{task.heading}\nO que a tarefa pede:\n{task.statement}\n\nEntregas exigidas:\n{items}\n\n"
        f"{_guide_block(guide)}{excerpts.strip()}{form}\n\n"
        "Resolva a tarefa por completo para esta organização. Entregue a solução pronta, com decisões "
        "concretas e justificadas (nomes de módulos, requisitos, configurações, quantidades, especificações), "
        "e não uma descrição do que deveria ser feito. Só use modelos e números de hardware se tiver certeza "
        "de que existem; na dúvida, descreva a especificação mínima. " + cover + SOLUTION_FORMAT
    )
    return _ask(ROLE + RULES, user, 2200)


def _closing(task: Task, solution: str, guide: str) -> str:
    user = (
        f"{task.heading}\n{_guide_block(guide)}Resumo da solução proposta:\n{solution[:2500]}\n\n"
        "Escreva dois parágrafos. No primeiro, a conclusão da etapa: como a solução resolve o problema da "
        "organização. No segundo, uma autoavaliação crítica em primeira pessoa, citando uma decisão acertada, "
        "uma dificuldade enfrentada e uma limitação concreta da proposta. Sem título e sem listas."
    )
    return _ask(ROLE + RULES, user, 600)


def _intro(theme: str, brief: Brief, norms: str) -> str:
    tasks = "\n".join(f"- {t.heading}: {t.statement[:300]}" for t in brief.tasks)
    form = f"Orientações gerais do trabalho:\n{norms}\n\n" if norms else ""
    user = (
        f"Tema do trabalho: {theme}\n\nEstudo de caso (fatos da organização):\n{brief.case_facts}\n\n"
        f"Tarefas resolvidas no desenvolvimento:\n{tasks}\n\n{form}"
        "Escreva a introdução: apresente a organização, seus produtos e seus gargalos com base nos fatos; "
        "depois declare o objetivo geral e os objetivos específicos (um por tarefa, em lista com '- '). "
        "Três a cinco parágrafos. Sem título."
    )
    return _ask(ROLE + RULES, user, 900)


def _conclusion(theme: str, brief: Brief, sections: list[dict], norms: str) -> str:
    summary = "\n".join(
        f"- {s['task'].heading}: {s['closing'].split(chr(10))[0][:400]}" for s in sections
    )
    form = f"Orientações gerais do trabalho:\n{norms}\n\n" if norms else ""
    user = (
        f"Tema do trabalho: {theme}\n\nEstudo de caso:\n{brief.case_facts}\n\nConclusões de cada etapa:\n{summary}\n\n"
        f"{form}"
        "Escreva a conclusão geral em três a quatro parágrafos: sintetize como as soluções se articulam para "
        "resolver os gargalos da organização, avalie o impacto na competitividade, na sustentabilidade e na "
        "confiança do cliente, e indique trabalhos futuros. Sem título e sem listas."
    )
    return _ask(ROLE + RULES, user, 900)


def _ask(system: str, user: str, num_predict: int) -> str:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    text = chat(messages, temperature=0.3, num_predict=num_predict)
    if FOREIGN_SCRIPT.search(text):
        # O Qwen às vezes muda para chinês no meio de respostas longas; uma nova amostra costuma sair limpa.
        messages[-1]["content"] += "\n\nResponda inteiramente em português do Brasil."
        text = chat(messages, temperature=0.2, num_predict=num_predict)
    return text


def assemble(title: str, intro: str, sections: list[dict], conclusion: str,
             references: list[str], gaps: list[str]) -> str:
    lines = [f"# {title}", "", "## 1 INTRODUÇÃO", "", intro, "", "## 2 DESENVOLVIMENTO", ""]
    for index, section in enumerate(sections, start=1):
        base = f"2.{index}"
        lines += [
            f"### {base} {section['task'].heading}", "",
            f"#### {base}.1 Fundamentação teórica", "", section["theory"] or "_(sem conteúdo)_", "",
            f"#### {base}.2 Solução proposta", "", _renumber(section["solution"], f"{base}.2"), "",
            f"#### {base}.3 Conclusão da etapa e autoavaliação", "", section["closing"], "",
        ]
    lines += ["## 3 CONCLUSÃO", "", conclusion, "", "## REFERÊNCIAS", ""]
    lines += [f"- {ref}" for ref in references] or ["Nenhuma fonte do acervo foi citada."]
    lines += ["", "---", "", "## Relatório de lacunas", "",
              "Este trecho não faz parte do trabalho. Ele lista o que foi removido ou ficou sem fonte.", ""]
    lines += [f"- {gap}" for gap in gaps] or ["- Nenhuma lacuna registrada."]
    return "\n".join(lines).strip() + "\n"


HEADING = re.compile(r"^\s*(#{1,6})\s+(.*)$")
# Fundamentação e conclusão têm seções próprias; as cópias que o modelo põe na solução são descartadas.
DUPLICATE_SECTION = re.compile(r"conclus|autoavalia|fundamenta|conceitua", re.IGNORECASE)


def _renumber(markdown: str, prefix: str) -> str:
    lines = _drop_empty_headings(_drop_duplicate_sections(markdown.splitlines()))
    levels = [len(m.group(1)) for m in _headings(lines).values()]
    top = min(levels) if levels else 1
    heads = _headings(lines)
    out: list[str] = []
    counters = [0, 0]
    for index, line in enumerate(lines):
        match = heads.get(index)
        if not match:
            out.append(line)
            continue
        depth = min(len(match.group(1)) - top, 1)
        text = _heading_text(match)
        counters[depth] += 1
        if depth == 0:
            counters[1] = 0
            out.append(f"##### {prefix}.{counters[0]} {text}")
        else:
            out.append(f"###### {prefix}.{max(counters[0], 1)}.{counters[1]} {text}")
    return "\n".join(out)


def _headings(lines: list[str]) -> dict[int, re.Match]:
    found, in_code = {}, False
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        match = None if in_code else HEADING.match(line)
        if match:
            found[index] = match
    return found


def _heading_text(match: re.Match) -> str:
    return re.sub(r"^(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s+", "", match.group(2)).replace("**", "").strip()


def _drop_duplicate_sections(lines: list[str]) -> list[str]:
    heads = _headings(lines)
    kept, skip_level = [], 0
    for index, line in enumerate(lines):
        match = heads.get(index)
        if match:
            level = len(match.group(1))
            if skip_level and level > skip_level:
                continue
            skip_level = level if DUPLICATE_SECTION.match(_heading_text(match)) or not _heading_text(match) else 0
            if skip_level:
                continue
        elif skip_level:
            continue
        kept.append(line)
    return kept


def _drop_empty_headings(lines: list[str]) -> list[str]:
    while True:
        heads = _headings(lines)
        empty = set()
        for index, match in heads.items():
            following = next((i for i in range(index + 1, len(lines)) if lines[i].strip()), None)
            if following is None:
                empty.add(index)
            elif following in heads and len(heads[following].group(1)) <= len(match.group(1)):
                empty.add(index)
        if not empty:
            return lines
        lines = [line for index, line in enumerate(lines) if index not in empty]


def _excerpts(chunks: list[Chunk]) -> str:
    blocks = []
    for chunk in chunks:
        heading = f" | seção {chunk.heading}" if chunk.heading else ""
        blocks.append(f"[{chunk.chunk_id}] {chunk.title or chunk.file}, p. {chunk.page}{heading}\n{chunk.text}")
    return "\n\n".join(blocks)


def _dedupe(chunks: list[Chunk], limit: int) -> list[Chunk]:
    seen: dict[str, Chunk] = {}
    for chunk in chunks:
        seen.setdefault(chunk.chunk_id, chunk)
        if len(seen) >= limit:
            break
    return list(seen.values())
