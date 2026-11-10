"""Clients for local model engines. Only loopback/LAN endpoints are allowed (no cloud APIs)."""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

from .. import config, db, net
from . import hw


class EngineError(RuntimeError):
    pass


def hf_dir(repo: str) -> Path:
    return config.models_dir() / "hf" / repo.replace("/", "--")


def gguf_dir() -> Path:
    d = config.models_dir() / "gguf"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _local_post(url: str, payload: dict, timeout: float = 180, stream: bool = False):
    if not net.allowed(url, "local"):
        raise EngineError(f"адрес не локальный: {url} (разрешены только 127.0.0.1 / локальная сеть)")
    import httpx
    c = httpx.Client(timeout=timeout, trust_env=False)
    if stream:
        return c, c.stream("POST", url, json=payload)
    try:
        r = c.post(url, json=payload)
    except httpx.HTTPError as e:
        raise EngineError(f"{url}: {e}") from e
    finally:
        c.close()
    if r.status_code != 200:
        raise EngineError(f"{url}: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


def _local_get(url: str, timeout: float = 5):
    if not net.allowed(url, "local"):
        raise EngineError(f"адрес не локальный: {url}")
    import httpx
    try:
        r = httpx.get(url, timeout=timeout, trust_env=False)
    except httpx.HTTPError as e:
        raise EngineError(str(e)) from e
    if r.status_code != 200:
        raise EngineError(f"HTTP {r.status_code}")
    return r.json()


# ---------------------------------------------------------------- Ollama helpers
def ollama_tags(url: str) -> list[dict]:
    try:
        return _local_get(url.rstrip("/") + "/api/tags").get("models", [])
    except EngineError:
        return []


def ollama_alive(url: str) -> bool:
    try:
        _local_get(url.rstrip("/") + "/api/version", timeout=2)
        return True
    except EngineError:
        return False


# ---------------------------------------------------------------- embeddings
_st_lock = threading.Lock()
_st_model = {"key": None, "m": None}

PREFIXES = {"intfloat/multilingual-e5": "passage: "}


def _prefix(model: str) -> str:
    return next((p for k, p in PREFIXES.items() if model.startswith(k)), "")


def embed(texts: list[str], cfg: dict | None = None) -> list[list[float]]:
    cfg = cfg or db.get_settings()["embed"]
    model = cfg.get("model") or ""
    if not model:
        raise EngineError("эмбеддинг-модель не выбрана")
    eng = cfg.get("engine", "st")
    if eng == "st":
        if not hw.has_module("sentence_transformers"):
            raise EngineError("пакет sentence-transformers не установлен (Модели → «Установить движок эмбеддингов»)")
        path = hf_dir(model)
        if not path.exists():
            raise EngineError(f"модель {model} не скачана")
        with _st_lock:
            key = (model, cfg.get("device", "auto"))
            if _st_model["key"] != key:
                from sentence_transformers import SentenceTransformer
                _st_model["m"] = None
                dev = hw.torch_device(cfg.get("device", "auto"))
                kw = {"model_kwargs": {"torch_dtype": "float16"}} if dev == "cuda" else {}
                _st_model["m"] = SentenceTransformer(str(path), device=dev, local_files_only=True, **kw)
                _st_model["key"] = key
            m = _st_model["m"]
            pre = _prefix(model)
            vecs = m.encode([pre + t for t in texts], batch_size=int(cfg.get("batch", 16)), normalize_embeddings=True,
                            show_progress_bar=False)
            return [list(map(float, v)) for v in vecs]
    url = cfg.get("url", "http://127.0.0.1:11434").rstrip("/")
    if eng == "ollama":
        j = _local_post(url + "/api/embed", {"model": model, "input": texts})
        return j["embeddings"]
    if eng == "openai":
        j = _local_post(url + "/v1/embeddings", {"model": model, "input": texts})
        return [d["embedding"] for d in j["data"]]
    raise EngineError(f"неизвестный движок {eng}")


def unload_embed() -> None:
    with _st_lock:
        _st_model.update(key=None, m=None)
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- LLM
def _extract_json(s: str) -> dict:
    s = re.sub(r"<think>.*?</think>", "", s or "", flags=re.S)
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        raise EngineError(f"LLM вернула не JSON: {s[:200]}")
    try:
        return json.loads(m.group(0))
    except ValueError as e:
        raise EngineError(f"LLM JSON parse: {e}: {s[:200]}") from e


def chat_json(system: str, user: str, schema: dict, cfg: dict | None = None, images: list[bytes] | None = None) -> dict:
    cfg = cfg or db.get_settings()["llm"]
    model = cfg.get("model") or ""
    if not model and cfg.get("engine") != "llamacpp":
        raise EngineError("LLM не выбрана")
    eng = cfg.get("engine", "ollama")
    timeout = float(cfg.get("timeout", 180))
    if eng == "ollama":
        url = cfg.get("url", "http://127.0.0.1:11434").rstrip("/")
        msg = {"role": "user", "content": user}
        if images:
            msg["images"] = [base64.b64encode(b).decode() for b in images]
        payload = {"model": model, "stream": False, "format": schema, "think": False,
                   "messages": [{"role": "system", "content": system}, msg],
                   "options": {"temperature": 0, "num_ctx": int(cfg.get("ctx", 8192))}}
        try:
            j = _local_post(url + "/api/chat", payload, timeout=timeout)
        except EngineError as e:
            if "think" in str(e):  # older Ollama / non-thinking model
                payload.pop("think")
                j = _local_post(url + "/api/chat", payload, timeout=timeout)
            else:
                raise
        return _extract_json(j.get("message", {}).get("content", ""))
    # OpenAI-compatible local servers (llama-server, LM Studio, vLLM, …)
    url = (LLAMA.url if eng == "llamacpp" else cfg.get("url", "")).rstrip("/")
    content: list | str = user
    if images:
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(b).decode()}} for b in images]
    payload = {"model": model or "local", "temperature": 0, "messages": [{"role": "system", "content": system},
                                                                          {"role": "user", "content": content}],
               "response_format": {"type": "json_object", "schema": schema}}
    j = _local_post(url + "/v1/chat/completions", payload, timeout=timeout)
    return _extract_json(j["choices"][0]["message"]["content"])


class LlamaServer:
    """Optional: start/stop llama.cpp's llama-server for a GGUF file chosen by the user."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.port = 8081
        self.url = f"http://127.0.0.1:{self.port}"

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, gguf: str, ngl: int = 99, ctx: int = 8192, binary: str = "llama-server") -> None:
        if self.running():
            return
        exe = shutil.which(binary) or (binary if Path(binary).exists() else None)
        if not exe:
            raise EngineError("llama-server не найден в PATH (установите llama.cpp или укажите путь)")
        if not Path(gguf).exists():
            raise EngineError(f"файл не найден: {gguf}")
        log = open(config.data_dir() / "llama-server.log", "ab")
        self.proc = subprocess.Popen([exe, "-m", gguf, "--host", "127.0.0.1", "--port", str(self.port),
                                      "-ngl", str(ngl), "-c", str(ctx)], stdout=log, stderr=log)

    def stop(self) -> None:
        if self.running():
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


LLAMA = LlamaServer()


def llm_status() -> dict:
    cfg = db.get_settings()["llm"]
    if cfg.get("engine") == "llamacpp":
        return {"ok": LLAMA.running(), "model": Path(cfg.get("gguf_path") or "").name or "—", "engine": "llama.cpp"}
    if not cfg.get("model"):
        return {"ok": False, "model": "—", "engine": cfg.get("engine")}
    if cfg.get("engine") == "ollama":
        names = {m.get("name") for m in ollama_tags(cfg["url"])}
        ok = cfg["model"] in names or f"{cfg['model']}:latest" in names
        return {"ok": ok, "model": cfg["model"], "engine": "ollama"}
    return {"ok": True, "model": cfg["model"], "engine": cfg.get("engine")}


# ---------------------------------------------------------------- vision
VISION_SCHEMA = {"type": "object", "properties": {"description": {"type": "string"}, "tone": {"type": "string"},
                                                  "style": {"type": "string"}}, "required": ["description"]}


def describe_image(img: bytes, cfg: dict | None = None) -> str:
    cfg = cfg or db.get_settings()["vision"]
    if not cfg.get("model"):
        raise EngineError("vision-модель не выбрана")
    j = chat_json("Ты описываешь превью YouTube-видео. Отвечай JSON.",
                  "Опиши кратко (1–2 предложения): что изображено, какой тон (юмор/серьёзно/кликбейт/агрессия), "
                  "стиль превью. Если на картинке есть текст — перепиши его.",
                  VISION_SCHEMA, cfg={**cfg, "timeout": 120}, images=[img])
    return " | ".join(str(j.get(k, "")) for k in ("description", "tone", "style") if j.get(k))


# ---------------------------------------------------------------- ASR
_asr = {"key": None, "m": None}


def transcribe(audio_path: Path, cfg: dict | None = None) -> tuple[str, str]:
    cfg = cfg or db.get_settings()["asr"]
    if not cfg.get("model"):
        raise EngineError("ASR-модель не выбрана")
    if not hw.has_module("faster_whisper"):
        raise EngineError("пакет faster-whisper не установлен (Модели → «Установить движок ASR»)")
    path = hf_dir(cfg["model"])
    if not path.exists():
        raise EngineError("ASR-модель не скачана")
    key = (cfg["model"], cfg.get("device"), cfg.get("compute_type"))
    if _asr["key"] != key:
        from faster_whisper import WhisperModel
        dev = cfg.get("device", "auto")
        if dev == "auto":
            dev = "cuda" if hw.gpu_info()["gpu"] else "cpu"
        ct = cfg.get("compute_type", "auto")
        if ct == "auto":
            ct = "int8_float16" if dev == "cuda" else "int8"
        _asr["m"] = WhisperModel(str(path), device=dev, compute_type=ct)
        _asr["key"] = key
    segs, info = _asr["m"].transcribe(str(audio_path), beam_size=1, vad_filter=True)
    return " ".join(s.text.strip() for s in segs), info.language
