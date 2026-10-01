import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf

from app.config import MAX_CHARS, TARGET_CHARS

BYLINE = re.compile(
    r"^(?P<author>.+?)[,.]?\s+(?P<year>(?:19|20)\d{2})\.?$"
)
PAGE_NUMBER = re.compile(r"^\d{1,3}$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# Convenção de nome para o acervo: "KENT,SOUPPAYA_2006_Guide to computer security log management.pdf"
FILENAME_META = re.compile(r"^(?P<authors>[^_]+)_(?P<year>(?:19|20)\d{2})_(?P<title>.+)$")


@dataclass
class Chunk:
    chunk_id: str
    text: str
    file: str
    page: int
    heading: str
    author: str
    year: str
    title: str = ""

    def to_payload(self) -> dict:
        return asdict(self)

    @classmethod
    def from_payload(cls, data: dict) -> "Chunk":
        return cls(
            chunk_id=str(data["chunk_id"]),
            text=str(data["text"]),
            file=str(data["file"]),
            page=int(data["page"]),
            heading=str(data.get("heading") or ""),
            author=str(data.get("author") or ""),
            year=str(data.get("year") or ""),
            title=str(data.get("title") or ""),
        )


def extract_chunks(paths: list[Path]) -> list[Chunk]:
    chunks: list[Chunk] = []
    next_id = 1
    for path in paths:
        produced, next_id = _chunks_from_pdf(path, next_id)
        chunks.extend(produced)
    if not chunks:
        raise ValueError(
            "Nenhum texto selecionável foi encontrado nos PDFs. "
            "O arquivo precisa ter texto, não só imagem."
        )
    return chunks


def _chunks_from_pdf(path: Path, next_id: int) -> tuple[list[Chunk], int]:
    document = pymupdf.open(path)
    blocks: list[dict] = []
    sizes: list[float] = []
    pdf_meta = document.metadata or {}
    try:
        for page in document:
            raw_blocks = []
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                raw_blocks.append(block)
            raw_blocks.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
            for block in raw_blocks:
                text, size = _block_text(block)
                if not text or PAGE_NUMBER.fullmatch(text):
                    continue
                blocks.append({"page": page.number + 1, "text": text, "size": size})
                if size:
                    sizes.append(size)
    finally:
        document.close()

    if not blocks:
        return [], next_id

    median = statistics.median(sizes) if sizes else 12
    author, year, title = source_metadata(path, pdf_meta, blocks)
    heading = ""
    buffer = ""
    buffer_page = blocks[0]["page"]
    chunks: list[Chunk] = []

    def flush() -> None:
        nonlocal buffer, next_id
        text = re.sub(r"\s+", " ", buffer).strip()
        buffer = ""
        if len(text) < 40:
            if text and chunks:
                chunks[-1].text = f"{chunks[-1].text} {text}".strip()
            return
        if chunks and chunks[-1].heading == heading and len(text) < 80:
            previous = chunks[-1]
            previous.text = f"{previous.text} {text}".strip()
            return
        chunks.append(
            Chunk(
                chunk_id=f"c{next_id}",
                text=text,
                file=path.name,
                page=buffer_page,
                heading=heading,
                author=author,
                year=year,
                title=title,
            )
        )
        next_id += 1

    for block in blocks:
        is_heading = _is_heading(block["text"], block["size"], median)
        if is_heading:
            flush()
            heading = block["text"]
            continue
        for piece in _split_long(block["text"]):
            if buffer and len(buffer) + 1 + len(piece) > TARGET_CHARS:
                flush()
            if not buffer:
                buffer_page = block["page"]
            buffer = f"{buffer} {piece}".strip()
    flush()
    return chunks, next_id


def _block_text(block: dict) -> tuple[str, float]:
    parts: list[str] = []
    sizes: list[float] = []
    for line in block.get("lines", []):
        line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
        if line_text:
            parts.append(line_text)
        sizes.extend(float(span.get("size", 0)) for span in line.get("spans", []))
    text = re.sub(r"\s+", " ", " ".join(parts)).strip()
    size = sum(sizes) / len(sizes) if sizes else 0
    return text, size


def _is_heading(text: str, size: float, median: float) -> bool:
    if len(text) > 140 or len(text.split()) > 16:
        return False
    if size >= median * 1.18 and size >= median + 1:
        return True
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and len(text) <= 80 and all(char.isupper() for char in letters)


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    pieces = SENTENCE_END.split(text)
    packed: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) > MAX_CHARS:
            packed.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        packed.append(current)
    final: list[str] = []
    for piece in packed:
        if len(piece) <= MAX_CHARS:
            final.append(piece)
            continue
        for start in range(0, len(piece), MAX_CHARS):
            final.append(piece[start : start + MAX_CHARS].strip())
    return [piece for piece in final if piece]


def source_metadata(path: Path, pdf_meta: dict, blocks: list[dict]) -> tuple[str, str, str]:
    """Autor (forma de citação ABNT), ano e título: nome do arquivo > metadados do PDF > linha de autoria."""
    match = FILENAME_META.match(path.stem)
    if match:
        authors = [a.strip() for a in match.group("authors").split(",") if a.strip()]
        return _cite_form(authors), match.group("year"), match.group("title").replace("-", " ").strip()
    meta_author = str(pdf_meta.get("author") or "").strip()
    meta_year = re.search(r"(?:19|20)\d{2}", str(pdf_meta.get("creationDate") or ""))
    meta_title = str(pdf_meta.get("title") or "").strip()
    if meta_author and meta_year:
        names = [n for n in re.split(r";|,| and | e |&", meta_author) if n.strip()]
        surnames = [n.split()[-1] for n in names if n.split()]
        return _cite_form(surnames), meta_year.group(0), meta_title
    author, year = _author_year(blocks)
    return author, year, meta_title


def _cite_form(surnames: list[str]) -> str:
    surnames = [s.upper() for s in surnames]
    if len(surnames) > 3:
        return f"{surnames[0]} et al."
    return "; ".join(surnames)


def _author_year(blocks: list[dict]) -> tuple[str, str]:
    early = [block["text"].strip() for block in blocks if block["page"] <= 2][:12]
    for line in early:
        match = BYLINE.match(line)
        if not match:
            continue
        author = match.group("author").strip(" .")
        if not author or author[0].isdigit() or len(author) > 80:
            continue
        words = author.split()
        if "," not in author and not (2 <= len(words) <= 6):
            continue
        return author, match.group("year")
    return "", ""
