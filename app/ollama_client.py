import time

import httpx

from app.config import CHAT_MODEL, CHAT_TIMEOUT, EMBED_MODEL, NUM_CTX, OLLAMA_URL


class OllamaError(RuntimeError):
    pass


def chat(messages: list[dict], *, json_mode: bool = False, temperature: float = 0.2, num_predict: int = 900) -> str:
    payload: dict = {
        "model": CHAT_MODEL,
        "messages": messages,
        "stream": False,
        "keep_alive": "20m",
        "options": {
            "temperature": temperature,
            "num_ctx": NUM_CTX,
            "num_predict": num_predict,
        },
    }
    if json_mode:
        payload["format"] = "json"
    try:
        with httpx.Client(timeout=httpx.Timeout(CHAT_TIMEOUT, connect=10.0)) as client:
            response = client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise OllamaError(f"Falha ao falar com o Ollama ({CHAT_MODEL}): {exc}") from exc
    content = (data.get("message") or {}).get("content", "").strip()
    if not content:
        raise OllamaError("Ollama devolveu uma resposta vazia.")
    return content


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors: list[list[float]] = []
    try:
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            for start in range(0, len(texts), 32):
                batch = texts[start : start + 32]
                response = client.post(
                    f"{OLLAMA_URL}/api/embed",
                    json={"model": EMBED_MODEL, "input": batch, "keep_alive": "20m"},
                )
                response.raise_for_status()
                got = response.json().get("embeddings")
                if not got or len(got) != len(batch):
                    raise OllamaError("A resposta de embedding não trouxe um vetor por trecho.")
                vectors.extend(got)
    except httpx.HTTPError as exc:
        raise OllamaError(f"Falha ao gerar embeddings ({EMBED_MODEL}): {exc}") from exc
    return vectors


def unload(model: str) -> None:
    try:
        httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "keep_alive": 0},
            timeout=30,
        )
    except httpx.HTTPError:
        return
    for _ in range(30):
        try:
            response = httpx.get(f"{OLLAMA_URL}/api/ps", timeout=10)
            response.raise_for_status()
            loaded = response.json().get("models") or []
        except httpx.HTTPError:
            return
        names = [str(item.get("name", "")) for item in loaded]
        if not any(name == model or name.startswith(f"{model}:") or model in name for name in names):
            return
        time.sleep(0.4)


def list_models() -> list[str]:
    response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10)
    response.raise_for_status()
    return [str(item.get("name", "")) for item in response.json().get("models") or []]
