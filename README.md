# academico-rag

Gera o trabalho (markdown e docx) a partir do enunciado e de PDFs de acervo. Roda na máquina, com Ollama e Qdrant. O enunciado define as tarefas e não entra como citação.

## Subir

```
docker compose up -d
ollama pull qwen2.5:7b
ollama pull bge-m3
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.\run.ps1
```

Abre http://127.0.0.1:8000

Ollama e Qdrant precisam estar no ar antes de gerar. Com 6 GB de VRAM o `run.ps1` deixa um modelo carregado por vez (`OLLAMA_MAX_LOADED_MODELS=1`).

PDF do acervo: `AUTOR,AUTOR_ANO_Titulo.pdf`. Sem esse padrão, autor e ano saem dos metadados do PDF, quando existem.

Os PDFs de exemplo e a saída gerada ficam de fora do repositório. O script `exemplo/rodar_job.py` espera o enunciado e a pasta `exemplo/acervo/`.
