"""Testes que não dependem do Ollama nem do Qdrant. Rodar: python -m tests.test_offline"""
from pathlib import Path

from app.brief import _clean, _tasks_by_headers, pdf_text
from app.generate import _renumber
from app.ingest import Chunk, source_metadata
from app.validate import clean_markdown

ROOT = Path(__file__).resolve().parents[2]
CHUNK = Chunk("c1", "Logs...", "KENT,SOUPPAYA_2006_Guide.pdf", 3, "", "KENT; SOUPPAYA", "2006", "Guide to log management")


def test_brief_camc() -> None:
    pdfs = list(ROOT.glob("PROJETO_INTEGRADO*.pdf"))
    if not pdfs:
        print("SKIP brief: PDF do enunciado não encontrado")
        return
    text = _clean(pdf_text(pdfs[0]))
    tasks, first = _tasks_by_headers(text)
    assert [t.number for t in tasks] == [1, 2, 3, 4, 5], [t.heading for t in tasks]
    assert tasks[0].heading.startswith("Passo 1: Projeto de Software"), tasks[0].heading
    assert "CRM" in tasks[0].statement
    assert any("Backlog" in d for d in tasks[0].deliverables), tasks[0].deliverables
    assert "NORMAS PARA" not in tasks[-1].statement
    assert "Contexto Prático" in text[:first]
    for task in tasks:
        print(" ", task.heading, "| entregas:", task.deliverables)


def test_validation_policy() -> None:
    md = "\n".join([
        "Logs devem ser centralizados [c1]. A tríade CIA orienta a segurança.",
        "Segundo Pressman (2021), requisitos importam. Isso vale (SOMMERVILLE, 2018).",
        "Conforme o enunciado, a empresa usa papel. Prezado aluno, bons estudos.",
        "- Item com citação inválida [c9].",
        "- Item bom [c1].",
        "| Nível | Uso |",
        "|---|---|",
        "| RAID 10 | banco [c1] |",
        "| RAID 5 | (STALLINGS, 2017) |",
        "```",
        "+--[ tela ]--+",
        "```",
    ])
    out, gaps, used = clean_markdown(md, [CHUNK])
    print(out)
    assert "(KENT; SOUPPAYA, 2006)" in out
    assert "A tríade CIA orienta a segurança." in out
    for removed in ("Pressman", "SOMMERVILLE", "enunciado", "Prezado", "[c9]", "STALLINGS"):
        assert removed not in out, removed
    assert "| RAID 10 | banco (KENT; SOUPPAYA, 2006) |" in out
    assert "+--[ tela ]--+" in out
    assert len(gaps) == 6, gaps
    assert [c.chunk_id for c in used] == ["c1"]


def test_filename_metadata() -> None:
    author, year, title = source_metadata(Path("FERRAIOLO,KUHN_1992_Role-based access controls.pdf"), {}, [])
    assert (author, year, title) == ("FERRAIOLO; KUHN", "1992", "Role based access controls"), (author, year, title)
    author, _, _ = source_metadata(Path("A,B,C,D_2000_X.pdf"), {}, [])
    assert author == "A et al."


def test_regressions_first_run() -> None:
    other = Chunk("c2", "RBAC...", "FERRAIOLO,KUHN_1992_RBAC.pdf", 1, "", "FERRAIOLO; KUHN", "1992", "RBAC")
    other_same = Chunk("c3", "RBAC 2...", "FERRAIOLO,KUHN_1992_RBAC.pdf", 2, "", "FERRAIOLO; KUHN", "1992", "RBAC")
    out, _, _ = clean_markdown("O RBAC, descrito em [c2] e [c3], restringe acessos.", [other, other_same])
    assert out == "O RBAC, descrito em Ferraiolo e Kuhn (1992), restringe acessos.", out
    out, _, _ = clean_markdown("Isso vale [c2][c1].", [other, CHUNK])
    assert "(FERRAIOLO; KUHN, 1992; KENT; SOUPPAYA, 2006)" in out, out

    broken = "Texto.\n```markdown\n```\nLab | Fábrica\n|---|---|\n```\n\n### Próximo\n```plaintext\n+--+\n```"
    out, _, _ = clean_markdown(broken, [])
    assert out.count("```") % 2 == 0, out
    assert out.index("### Próximo") > out.index("|---|"), out

    fenced_table = "```markdown\n| A | B |\n|---|---|\n| 1 | 2 |\n```"
    out, _, _ = clean_markdown(fenced_table, [])
    assert "```" not in out and "| 1 | 2 |" in out, out

    unclosed, _, _ = clean_markdown("```\n+--+", [])
    assert unclosed.endswith("```"), unclosed

    from app.validate import bibliography
    etal = Chunk("c4", "x", "f.pdf", 1, "", "BARKER et al.", "2020", "Guide to IPsec VPNs")
    assert bibliography([etal]) == ["BARKER et al. **Guide to IPsec VPNs**. 2020."]


def test_split_norms() -> None:
    from app.brief import split_norms
    norms = "\n".join([
        "# PAPEL", "Você é engenheiro.", "#### 2. DESENVOLVIMENTO",
        "* **PASSO 1: CRM**", "  - Backlog com RF e RNF.",
        "* **PASSO 2: SEGURANÇA**", "  - RBAC: Operador de Campo, Financeiro.",
        "#### 3. CONCLUSÃO", "- Síntese geral.",
    ])
    general, per_task = split_norms(norms)
    assert set(per_task) == {1, 2}, per_task
    assert "Backlog" in per_task[1] and "RBAC" not in per_task[1]
    assert "Operador de Campo" in per_task[2] and "CONCLUSÃO" not in per_task[2]
    assert "Síntese geral" in general and "engenheiro" in general and "RBAC" not in general


def test_renumber() -> None:
    out = _renumber(
        "## 1. Backlog\ntexto\n```\n# não é título\n```\n### **Kanban**\ncolunas\n### Vazio\n"
        "## Fundamentação Teórica\n### RBAC\ncópia\n## 2. Matriz\ntabela\n### Conclusão\nfim.",
        "2.1.2",
    )
    assert "##### 2.1.2.1 Backlog" in out and "###### 2.1.2.1.1 Kanban" in out, out
    assert "# não é título" in out and "##### 2.1.2.2 Matriz" in out, out
    assert "Vazio" not in out and "cópia" not in out and "RBAC" not in out, out
    assert "Conclusão" not in out and "fim." not in out, out


def test_citation_policy_extras() -> None:
    text, gaps, _ = clean_markdown("Segurança exige controle de acesso [p1]. Outra frase [c1].", [],
                                   allow_citations=False)
    assert "[p1]" not in text and "[c1]" not in text and "Outra frase" in text, (text, gaps)
    text, gaps, _ = clean_markdown(
        "De acordo com Nielsen, existem sete heurísticas. Conforme o Quadro 2, há três perfis. "
        "Conforme a regra de negócio, o acesso é restrito.", [])
    assert "Nielsen" not in text and "Quadro 2" in text and "regra de negócio" in text, (text, gaps)
    text, _, _ = clean_markdown("Usa heurísticas, conforme proposto por Jakob Nielsen. O fluxo tem três cliques.", [])
    assert "Nielsen" not in text and "três cliques" in text, text


def test_model_degeneration() -> None:
    text, gaps, _ = clean_markdown("Texto bom.\n\n##### 2.2.2.4 安全计划\n信息安全", [])
    assert text == "Texto bom." and any("idioma" in g for g in gaps), (text, gaps)
    text, _, _ = clean_markdown("```\n+--+\n" + "   |   |\n" * 300 + "```", [])
    assert text.count("|   |") == 3, text
    text, _, _ = clean_markdown("Segundo [c1], logs são centrais. Um  teste  com espaços.", [CHUNK])
    assert text == "Segundo Kent e Souppaya (2006), logs são centrais. Um teste com espaços.", text
    loop = "O firewall suporta IPSec, " + "firewall de rede de segurança, " * 40 + "fim."
    text, gaps, _ = clean_markdown("- " + loop, [])
    assert text.count("firewall de rede de segurança") == 1 and len(text) < 120, text
    table = "| Diário | Incremental | Diariamente | Sim | Sim |\n| Semanal | Full | Semanalmente | Sim | Sim |"
    text, _, _ = clean_markdown("| Nível | Tipo | Frequência | Local | Remoto |\n|---|---|---|---|---|\n" + table, [])
    assert text.endswith(table), text
    diagram = "```\n| Título         |       | Título         |       | Título         |       | Título  |\n```"
    text, gaps, _ = clean_markdown(diagram, [])
    assert text == diagram and not gaps, (text, gaps)


def test_citation_forms() -> None:
    rbac = Chunk("c2", "RBAC...", "FERRAIOLO,KUHN_1992_RBAC.pdf", 1, "", "FERRAIOLO; KUHN", "1992", "RBAC")
    text, _, _ = clean_markdown("O RBAC associa papéis a permissões [c2, c1].", [rbac, CHUNK])
    assert text == "O RBAC associa papéis a permissões (FERRAIOLO; KUHN, 1992; KENT; SOUPPAYA, 2006).", text
    text, _, _ = clean_markdown("Além disso, [c2] mostra que papéis simplificam a gestão.", [rbac])
    assert text == "Além disso, Ferraiolo e Kuhn (1992) mostra que papéis simplificam a gestão.", text
    text, _, _ = clean_markdown("O acesso é por papel, conforme sugerido no trecho [c2].", [rbac])
    assert text == "O acesso é por papel, conforme sugerido (FERRAIOLO; KUHN, 1992).", text
    text, gaps, _ = clean_markdown(
        "Jakob Nielsen, um renomado especialista, propôs heurísticas [c2]. Ferraiolo e Kuhn definiu papéis [c2]. "
        "A Barra Energética apresenta alta procura.", [rbac])
    assert "Nielsen" not in text and "Ferraiolo e Kuhn" in text and "Barra Energética" in text, (text, gaps)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
