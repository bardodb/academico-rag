"""Limpa o markdown gerado: citação inventada, frase do enunciado e marcador [cN] inválido saem."""
import re

from app.ingest import Chunk

CITE = re.compile(r"[\[(（【]\s*(c\d+)\s*[\])）】]")
CITE_RUN = re.compile(r"(?:[\[(（【]\s*c\d+\s*[\])）】]\s*(?:[,;e]\s*)?)*[\[(（【]\s*c\d+\s*[\])）】]")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9(\"“])")
UPPER = "A-ZÁÉÍÓÚÂÊÔÃÕÇ"
NAME = rf"[{UPPER}][A-Za-zÀ-ÿ'\-]+"
FAKE_CITATION = re.compile(
    rf"\(\s*{NAME}(?:\s+et\s+al\.)?(?:\s*[;,&]\s*{NAME})*\s*,\s*(?:19|20)\d{{2}}[a-z]?(?:\s*,\s*p\.\s*[\d\-]+)?\s*\)"
    rf"|\b{NAME}(?:\s+(?:e|and|&)\s+{NAME})?(?:\s+et\s+al\.)?\s*\(\s*(?:19|20)\d{{2}}[a-z]?\s*\)"
)
INSTITUTIONAL = re.compile(
    r"prezad[oa]|seja bem[- ]vind|bons estudos|desejamos|caro\(a\) aluno|querid[oa] alun|"
    r"\bAVA\b|tutor(?:ia)? a dist[âa]ncia|valer[áa] \d+ pontos|crit[ée]rios? de corre[çc][ãa]o",
    re.IGNORECASE,
)
BRIEF_AS_SOURCE = re.compile(
    r"(?:segundo|conforme|de acordo com|como (?:descrito|indicado|solicitado) n)[oa]? "
    r"(?:o |a )?(?:enunciado|pdf|documento (?:da institui[çc][ãa]o|do projeto)|material do curso|roteiro)",
    re.IGNORECASE,
)
LIST_PREFIX = re.compile(r"^(\s*(?:[-*•]|\d+[.)])\s+)")
STRAY_MARKER = re.compile(r"\s*\[(?:p|ref|fonte|nota|passo)?\s*\d+\]", re.IGNORECASE)
FOREIGN_SCRIPT = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
MAX_REPEATED_LINES = 3
LOOP_SHINGLE = 5
CITE_LIST = re.compile(r"[\[(]\s*(c\d+(?:\s*[,;]\s*c\d+)+)\s*[\])]")
YEAR = r"((?:19|20)\d{2}|\[s\.d\.\])"
NARRATIVE_CITE = re.compile(rf"\b((?i:segundo|conforme|de acordo com|em|por))\s+\(([^(),]+), {YEAR}\)")
NARRATIVE_START = re.compile(rf"(^|(?<=[.!?] )|(?:Além disso|Ainda|Também|Por sua vez), )\(([^(),]+), {YEAR}\)(?=\s+[a-zà-ÿ])")
PERSON = rf"[{UPPER}][a-zà-ÿ'\-]+"
UNSOURCED_ATTRIBUTION = re.compile(
    rf"\b(?i:segundo|conforme|de acordo com|como afirma|como prop[õo]e|(?:propost|definid|desenvolvid|criad)[oa]s? por)"
    rf"\s+(?:o |a )?"
    rf"(?!Quadro|Figura|Tabela|Se[çc][ãa]o|Passo|Cap[íi]tulo|Anexo|Ap[êe]ndice|Lei\b)"
    rf"({PERSON}(?:\s+{PERSON})?)"
)
PERSON_CLAIM = re.compile(
    rf"^\s*({PERSON} {PERSON})(?:,[^,]{{0,80}},)?\s+(?:prop[ôo]s|prop[õo]e|definiu|afirm(?:a|ou)|sugeriu|descreveu)\b"
)


def clean_markdown(text: str, chunks: list[Chunk], allow_citations: bool = True) -> tuple[str, list[str], list[Chunk]]:
    """Com allow_citations=False os [cN] são apagados (introdução e conclusões não citam o acervo)."""
    text = STRAY_MARKER.sub("", text)
    text = CITE_LIST.sub(lambda m: "".join(f"[{i}]" for i in re.findall(r"c\d+", m.group(1))), text)
    if not allow_citations:
        text = CITE.sub("", text)
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    gaps: list[str] = []
    used: list[Chunk] = []
    out: list[str] = []
    in_code = False
    lines = _strip_wrapping_fence(text).splitlines()
    foreign = next((i for i, ln in enumerate(lines) if FOREIGN_SCRIPT.search(ln)), None)
    if foreign is not None:
        gaps.append("O modelo mudou de idioma no meio da seção; o texto a partir desse ponto foi descartado.")
        lines = lines[:foreign]
    for raw in _collapse_repeats(_normalize_fences(lines)):
        line = raw.rstrip()
        if line.strip().startswith("```"):
            in_code = not in_code
            out.append(line.strip())
            continue
        if in_code or not line.strip():
            out.append(line)
            continue
        line, looped = _cut_loop(line)
        if looped:
            gaps.append("O modelo entrou em repetição dentro de uma linha; a repetição foi cortada.")
        if line.lstrip().startswith("#"):
            out.append(CITE.sub("", line).rstrip())
            continue
        if line.lstrip().startswith("|"):
            cells, cell_gaps, cell_used = _check_fragment(line, by_id)
            gaps.extend(cell_gaps)
            used.extend(cell_used)
            if cells is not None:
                out.append(cells)
            continue
        prefix_match = LIST_PREFIX.match(line)
        prefix = prefix_match.group(1) if prefix_match else ""
        body = line[len(prefix):]
        kept = []
        for sentence in _sentences(body):
            fixed, sentence_gaps, sentence_used = _check_fragment(sentence, by_id)
            gaps.extend(sentence_gaps)
            used.extend(sentence_used)
            if fixed:
                kept.append(fixed)
        if kept:
            out.append(prefix + re.sub(r"(?<=\S) {2,}", " ", " ".join(kept)))
    if in_code:
        out.append("```")
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return cleaned, _unique(gaps), _unique_chunks(used)


def _normalize_fences(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip().startswith("```"):
            out.append(line)
            i += 1
            continue
        end = next((j for j in range(i + 1, len(lines)) if lines[j].strip().startswith("```")), None)
        if end == i + 1:
            i += 1  # cerca vazia abrindo antes de outra: a segunda passa a abrir o bloco
            continue
        if end is not None:
            inner = [ln for ln in lines[i + 1:end] if ln.strip()]
            is_table = any(re.match(r"^\s*\|\s*:?-{3,}", ln) for ln in inner)
            if inner and is_table and all(ln.lstrip().startswith("|") for ln in inner):
                out.extend(lines[i + 1:end])  # tabela Markdown cercada: desembrulha
                i = end + 1
                continue
            out.extend(lines[i:end + 1])
            i = end + 1
            continue
        out.append(line)
        i += 1
    return out


def _collapse_repeats(lines: list[str]) -> list[str]:
    out: list[str] = []
    run = 0
    for line in lines:
        run = run + 1 if out and line.strip() and line.strip() == out[-1].strip() else 1
        if run <= MAX_REPEATED_LINES:
            out.append(line)
    return out


def _cut_loop(line: str) -> tuple[str, bool]:
    # célula de tabela repete de propósito
    if line.lstrip().startswith("|"):
        return line, False
    words = [m for m in re.finditer(r"[\wÀ-ÿ'\-]+", line)]
    seen: dict[tuple[str, ...], list[int]] = {}
    for i in range(len(words) - LOOP_SHINGLE + 1):
        positions = seen.setdefault(tuple(w.group(0).lower() for w in words[i:i + LOOP_SHINGLE]), [])
        if positions and i - positions[-1] < LOOP_SHINGLE:
            continue
        positions.append(i)
        if len(positions) == 3:
            return line[:words[positions[1]].start()].rstrip(" ,;:") + ".", True
    return line, False


def _check_fragment(fragment: str, by_id: dict[str, Chunk]):
    stripped = fragment.strip()
    short = stripped if len(stripped) <= 160 else stripped[:160].rstrip() + "…"
    if INSTITUTIONAL.search(fragment):
        return None, [f"Removida frase institucional: {short}"], []
    if BRIEF_AS_SOURCE.search(fragment):
        return None, [f"Removida frase que usava o enunciado como fonte: {short}"], []
    ids = CITE.findall(fragment)
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        return None, [f"Removida citação a trecho inexistente ({', '.join(unknown)}): {short}"], []
    without_ids = CITE.sub("", fragment)
    if FAKE_CITATION.search(without_ids):
        return None, [f"Removida citação sem trecho no acervo: {short}"], []
    names = [m.group(1) for m in UNSOURCED_ATTRIBUTION.finditer(without_ids)]
    names += [m.group(1) for m in PERSON_CLAIM.finditer(without_ids)]
    if names and not ids:
        return None, [f"Removida atribuição a autor sem trecho no acervo: {short}"], []
    if names:
        cited = " ".join(by_id[i].author or "" for i in ids).lower()
        if any(name.split()[-1].lower() not in cited for name in names):
            return None, [f"Removida atribuição a autor diferente do trecho citado: {short}"], []
    replaced, gaps, used = _apply_citations(fragment, by_id)
    return replaced, gaps, used


def _apply_citations(text: str, by_id: dict[str, Chunk]) -> tuple[str, list[str], list[Chunk]]:
    gaps: list[str] = []
    used: list[Chunk] = []

    def replace_run(match: re.Match) -> str:
        labels: list[str] = []
        for chunk_id in CITE.findall(match.group(0)):
            chunk = by_id[chunk_id]
            used.append(chunk)
            if not chunk.author or not chunk.year:
                gaps.append(f"O arquivo {chunk.file} não tem autor e ano identificáveis; renomeie como "
                            "AUTOR,AUTOR_ANO_Título.pdf.")
            if cite_label(chunk) not in labels:
                labels.append(cite_label(chunk))
        return f"({'; '.join(labels)})"

    result = CITE_RUN.sub(replace_run, text)
    result = re.sub(r"(\([^()]+\))(?:\s*(?:e|,)\s*\1)+", r"\1", result)
    result = re.sub(r"\s+(?:n|d|pel)[oa]s? trechos?\s+(?=\()", " ", result)
    result = NARRATIVE_CITE.sub(lambda m: f"{m.group(1)} {_narrative(m.group(2), m.group(3))}", result)
    result = NARRATIVE_START.sub(lambda m: m.group(1) + _narrative(m.group(2), m.group(3)), result)
    result = re.sub(r"\s+([.,;:])", r"\1", result)
    return result.strip(), gaps, used


def _narrative(authors: str, year: str) -> str:
    """"Segundo (KENT; SOUPPAYA, 2006)" vira "Segundo Kent e Souppaya (2006)", como pede a NBR 10520."""
    names = [n.strip() for n in authors.split(";")]
    names = [re.sub(r"\b([A-ZÀ-Ý])([A-ZÀ-Ý'\-]+)\b", lambda m: m.group(1) + m.group(2).lower(), n) for n in names]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " e " + names[-1]
    return f"{joined} ({year})"


def cite_label(chunk: Chunk) -> str:
    author = chunk.author or (chunk.title or chunk.file).split()[0].upper()
    return f"{author}, {chunk.year or '[s.d.]'}"


def bibliography(chunks: list[Chunk]) -> list[str]:
    refs: dict[str, str] = {}
    for chunk in chunks:
        if chunk.file in refs:
            continue
        author = chunk.author or (chunk.title or chunk.file).split()[0].upper()
        title = chunk.title or chunk.file.rsplit(".", 1)[0]
        refs[chunk.file] = f"{author.rstrip('.')}. **{title}**. {chunk.year or '[s.d.]'}."
    return sorted(refs.values(), key=str.lower)


def _strip_wrapping_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(markdown|md)?\s*\n(.*)\n```", stripped, re.DOTALL)
    if match and (match.group(1) or re.search(r"^#{1,6} ", match.group(2), re.M)):
        return match.group(2)
    return stripped


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_END.split(text) if p.strip()]
    merged: list[str] = []
    cite_only = re.compile(r"(?:[\[(（【]\s*c\d+\s*[\])）】]\s*)+[.]?")
    for part in parts:
        if cite_only.fullmatch(part) and merged:
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _unique_chunks(chunks: list[Chunk]) -> list[Chunk]:
    seen: dict[str, Chunk] = {}
    for chunk in chunks:
        seen.setdefault(chunk.chunk_id, chunk)
    return list(seen.values())
