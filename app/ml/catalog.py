"""Model catalog. Sizes/VRAM are approximate (≈) and licenses must be re-checked on the model page
before use — they change. Nothing here is downloaded unless the user clicks "Скачать".

engine: st (sentence-transformers, HF repo) | ollama (tag) | whisper (faster-whisper CT2 repo) | gguf (HF repo, file picked by user)
open: True for OSI-style permissive/copyleft licenses (Apache-2.0, MIT, BSD, GPL…); False for custom/"community"/NC.
"""
from __future__ import annotations

OPEN_LICENSES = {"Apache-2.0", "MIT", "BSD-3-Clause", "BSD-2-Clause", "GPL-3.0", "LGPL-3.0", "MPL-2.0"}


def M(id, kind, engine, ref, name, disk, vram, langs, license, params="", notes=""):
    return {"id": id, "kind": kind, "engine": engine, "ref": ref, "name": name, "disk_gb": disk, "vram": vram,
            "langs": langs, "license": license, "open": license in OPEN_LICENSES, "params": params, "notes": notes}


ML = "100+ языков"
CATALOG = [
    # ---------------- embeddings (sentence-transformers)
    M("e5-small", "embed", "st", "intfloat/multilingual-e5-small", "multilingual-e5-small", 0.47, {"fp16": 0.4}, ML, "MIT", "118M", "Быстрая, хороший старт для режима «Средний»."),
    M("e5-base", "embed", "st", "intfloat/multilingual-e5-base", "multilingual-e5-base", 1.1, {"fp16": 0.7}, ML, "MIT", "278M"),
    M("e5-large", "embed", "st", "intfloat/multilingual-e5-large", "multilingual-e5-large", 2.2, {"fp16": 1.4}, ML, "MIT", "560M"),
    M("e5-large-instruct", "embed", "st", "intfloat/multilingual-e5-large-instruct", "multilingual-e5-large-instruct", 2.2, {"fp16": 1.4}, ML, "MIT", "560M"),
    M("bge-m3", "embed", "st", "BAAI/bge-m3", "bge-m3", 2.3, {"fp16": 1.6}, ML, "MIT", "568M", "Длинный контекст (8k), сильная многоязычная."),
    M("user-bge-m3", "embed", "st", "deepvk/USER-bge-m3", "USER-bge-m3 (ru)", 1.4, {"fp16": 1.5}, "ru (+en)", "Apache-2.0", "359M", "Дообучена на русском."),
    M("frida", "embed", "st", "ai-forever/FRIDA", "FRIDA (ru+en)", 3.3, {"fp16": 2.0}, "ru, en", "MIT", "823M"),
    M("qwen3-emb-0.6b", "embed", "st", "Qwen/Qwen3-Embedding-0.6B", "Qwen3-Embedding-0.6B", 1.2, {"fp16": 1.6}, ML, "Apache-2.0", "0.6B"),
    M("qwen3-emb-4b", "embed", "st", "Qwen/Qwen3-Embedding-4B", "Qwen3-Embedding-4B", 8.0, {"fp16": 8.5}, ML, "Apache-2.0", "4B", "Не влезает в 8 ГБ в fp16."),
    M("arctic-l-v2", "embed", "st", "Snowflake/snowflake-arctic-embed-l-v2.0", "snowflake-arctic-embed-l-v2.0", 2.2, {"fp16": 1.4}, ML, "Apache-2.0", "568M"),
    M("mpnet-ml", "embed", "st", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2", "paraphrase-multilingual-mpnet-base-v2", 1.1, {"fp16": 0.7}, "50+ языков", "Apache-2.0", "278M"),
    M("minilm-ml", "embed", "st", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "paraphrase-multilingual-MiniLM-L12-v2", 0.47, {"fp16": 0.3}, "50+ языков", "Apache-2.0", "118M", "Самая лёгкая, работает и на CPU."),
    M("jina-v3", "embed", "st", "jinaai/jina-embeddings-v3", "jina-embeddings-v3", 1.1, {"fp16": 1.2}, ML, "CC-BY-NC-4.0", "570M", "Некоммерческая лицензия, нужен trust_remote_code."),
    M("embeddinggemma", "embed", "st", "google/embeddinggemma-300m", "EmbeddingGemma-300m", 1.2, {"fp16": 0.7}, ML, "Gemma", "300M", "Gemma Terms of Use."),
    # embeddings through Ollama
    M("ollama-bge-m3", "embed", "ollama", "bge-m3", "bge-m3 (Ollama)", 1.2, {"fp16": 1.5}, ML, "MIT", "568M"),
    M("ollama-qwen3-emb", "embed", "ollama", "qwen3-embedding:0.6b", "qwen3-embedding:0.6b (Ollama)", 0.64, {"Q8": 1.0}, ML, "Apache-2.0", "0.6B"),
    M("ollama-arctic2", "embed", "ollama", "snowflake-arctic-embed2", "snowflake-arctic-embed2 (Ollama)", 1.2, {"fp16": 1.4}, ML, "Apache-2.0", "568M"),

    # ---------------- LLM (Ollama tags; VRAM ≈ Q4_K_M weights + 8k context)
    M("qwen3-4b", "llm", "ollama", "qwen3:4b", "Qwen3 4B", 2.5, {"Q4_K_M": 3.5, "Q8_0": 5.2}, ML, "Apache-2.0", "4B", "Хороший баланс для 8 ГБ."),
    M("qwen3-8b", "llm", "ollama", "qwen3:8b", "Qwen3 8B", 5.2, {"Q4_K_M": 6.2, "Q8_0": 9.5}, ML, "Apache-2.0", "8B"),
    M("qwen3-14b", "llm", "ollama", "qwen3:14b", "Qwen3 14B", 9.3, {"Q4_K_M": 10.5}, ML, "Apache-2.0", "14B", "Частичный оффлоад в RAM."),
    M("qwen3-30b-a3b", "llm", "ollama", "qwen3:30b", "Qwen3 30B-A3B (MoE)", 19.0, {"Q4_K_M": 19.5}, ML, "Apache-2.0", "30B/3B акт.", "MoE: быстро даже с оффлоадом, нужно ~24 ГБ RAM+VRAM."),
    M("qwen2.5-7b", "llm", "ollama", "qwen2.5:7b", "Qwen2.5 7B", 4.7, {"Q4_K_M": 5.8}, ML, "Apache-2.0", "7B"),
    M("qwen2.5-3b", "llm", "ollama", "qwen2.5:3b", "Qwen2.5 3B", 1.9, {"Q4_K_M": 2.8}, ML, "Qwen-Research", "3B", "Исследовательская лицензия."),
    M("gemma3-4b", "llm", "ollama", "gemma3:4b", "Gemma 3 4B", 3.3, {"Q4_K_M": 4.2}, ML, "Gemma", "4B", "Также vision."),
    M("gemma3-12b", "llm", "ollama", "gemma3:12b", "Gemma 3 12B", 8.1, {"Q4_K_M": 9.5}, ML, "Gemma", "12B"),
    M("mistral-7b", "llm", "ollama", "mistral:7b", "Mistral 7B Instruct", 4.1, {"Q4_K_M": 5.2}, "en, ru (слабее)", "Apache-2.0", "7B"),
    M("mistral-nemo", "llm", "ollama", "mistral-nemo:12b", "Mistral-Nemo 12B", 7.1, {"Q4_K_M": 8.3}, ML, "Apache-2.0", "12B", "Хороший русский; почти впритык к 8 ГБ."),
    M("ministral-3-8b", "llm", "ollama", "ministral-3:8b", "Ministral 3 8B", 6.0, {"Q4_K_M": 6.5}, ML, "Apache-2.0", "8B", "Проверьте актуальный тег в библиотеке Ollama."),
    M("mistral-small-24b", "llm", "ollama", "mistral-small3.2:24b", "Mistral Small 3.2 24B", 15.0, {"Q4_K_M": 16.0}, ML, "Apache-2.0", "24B", "Оффлоад, медленно."),
    M("phi4-mini", "llm", "ollama", "phi4-mini", "Phi-4-mini 3.8B", 2.5, {"Q4_K_M": 3.5}, "en (+ru слабее)", "MIT", "3.8B"),
    M("phi4-14b", "llm", "ollama", "phi4:14b", "Phi-4 14B", 9.1, {"Q4_K_M": 10.5}, "en (+ru)", "MIT", "14B"),
    M("granite3.3-8b", "llm", "ollama", "granite3.3:8b", "Granite 3.3 8B", 4.9, {"Q4_K_M": 6.0}, "12 языков", "Apache-2.0", "8B"),
    M("olmo2-7b", "llm", "ollama", "olmo2:7b", "OLMo 2 7B", 4.5, {"Q4_K_M": 5.5}, "en", "Apache-2.0", "7B", "Полностью открытая (данные и код)."),
    M("gpt-oss-20b", "llm", "ollama", "gpt-oss:20b", "gpt-oss 20B (MoE)", 14.0, {"MXFP4": 14.0}, ML, "Apache-2.0", "21B/3.6B акт.", "Оффлоад в RAM."),
    M("deepseek-r1-8b", "llm", "ollama", "deepseek-r1:8b", "DeepSeek-R1 distill 8B", 5.2, {"Q4_K_M": 6.2}, ML, "MIT", "8B", "Рассуждающая: медленнее."),
    M("deepseek-r1-14b", "llm", "ollama", "deepseek-r1:14b", "DeepSeek-R1 distill 14B", 9.0, {"Q4_K_M": 10.5}, ML, "MIT", "14B"),
    M("llama3.2-3b", "llm", "ollama", "llama3.2:3b", "Llama 3.2 3B", 2.0, {"Q4_K_M": 3.0}, "8 языков", "Llama-Community", "3B"),
    M("llama3.1-8b", "llm", "ollama", "llama3.1:8b", "Llama 3.1 8B", 4.9, {"Q4_K_M": 6.0}, "8 языков", "Llama-Community", "8B"),
    M("glm4-9b", "llm", "ollama", "glm4:9b", "GLM-4 9B", 5.5, {"Q4_K_M": 6.8}, ML, "GLM-4", "9B"),
    M("aya-8b", "llm", "ollama", "aya-expanse:8b", "Aya Expanse 8B", 5.1, {"Q4_K_M": 6.2}, "23 языка", "CC-BY-NC-4.0", "8B"),
    M("vikhr-nemo-gguf", "llm", "gguf", "Vikhrmodels/Vikhr-Nemo-12B-Instruct-R-21-09-24-GGUF", "Vikhr-Nemo 12B (ru, GGUF)", 7.5, {"Q4_K_M": 8.3}, "ru, en", "Apache-2.0", "12B", "GGUF для llama.cpp: выберите файл."),
    M("qwen3-8b-gguf", "llm", "gguf", "Qwen/Qwen3-8B-GGUF", "Qwen3 8B (GGUF)", 5.0, {"Q4_K_M": 6.2}, ML, "Apache-2.0", "8B", "GGUF для llama.cpp: выберите файл."),

    # ---------------- vision (Ollama)
    M("qwen3-vl-4b", "vision", "ollama", "qwen3-vl:4b", "Qwen3-VL 4B", 3.3, {"Q4_K_M": 4.5}, ML, "Apache-2.0", "4B"),
    M("qwen3-vl-8b", "vision", "ollama", "qwen3-vl:8b", "Qwen3-VL 8B", 6.1, {"Q4_K_M": 7.0}, ML, "Apache-2.0", "8B"),
    M("qwen2.5vl-7b", "vision", "ollama", "qwen2.5vl:7b", "Qwen2.5-VL 7B", 6.0, {"Q4_K_M": 7.0}, ML, "Apache-2.0", "7B"),
    M("qwen2.5vl-3b", "vision", "ollama", "qwen2.5vl:3b", "Qwen2.5-VL 3B", 3.2, {"Q4_K_M": 4.0}, ML, "Qwen-Research", "3B"),
    M("moondream", "vision", "ollama", "moondream", "moondream2 1.8B", 1.7, {"Q4": 2.2}, "en", "Apache-2.0", "1.8B", "Очень лёгкая, описывает по-английски."),
    M("granite3.2-vision", "vision", "ollama", "granite3.2-vision", "Granite 3.2 Vision 2B", 2.4, {"Q4_K_M": 3.0}, "en", "Apache-2.0", "2B"),
    M("llava-7b", "vision", "ollama", "llava:7b", "LLaVA 1.6 (Mistral 7B)", 4.7, {"Q4_0": 5.5}, "en", "Apache-2.0", "7B"),
    M("gemma3-4b-vision", "vision", "ollama", "gemma3:4b", "Gemma 3 4B (vision)", 3.3, {"Q4_K_M": 4.5}, ML, "Gemma", "4B"),
    M("minicpm-v", "vision", "ollama", "minicpm-v", "MiniCPM-V 8B", 5.5, {"Q4_K_M": 6.5}, ML, "MiniCPM", "8B"),

    # ---------------- ASR (faster-whisper / CTranslate2)
    M("whisper-tiny", "asr", "whisper", "Systran/faster-whisper-tiny", "Whisper tiny", 0.08, {"int8": 0.3}, ML, "MIT", "39M"),
    M("whisper-base", "asr", "whisper", "Systran/faster-whisper-base", "Whisper base", 0.15, {"int8": 0.4}, ML, "MIT", "74M"),
    M("whisper-small", "asr", "whisper", "Systran/faster-whisper-small", "Whisper small", 0.48, {"int8": 0.8}, ML, "MIT", "244M"),
    M("whisper-medium", "asr", "whisper", "Systran/faster-whisper-medium", "Whisper medium", 1.5, {"int8": 1.8, "fp16": 2.6}, ML, "MIT", "769M"),
    M("whisper-large-v3", "asr", "whisper", "Systran/faster-whisper-large-v3", "Whisper large-v3", 3.1, {"int8": 3.0, "fp16": 4.5}, ML, "MIT", "1.55B"),
    M("whisper-large-v3-turbo", "asr", "whisper", "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "Whisper large-v3-turbo", 1.6, {"int8": 1.8, "fp16": 3.0}, ML, "MIT", "809M", "Лучшее соотношение скорость/качество."),
]

KINDS = {"embed": "Эмбеддинги", "llm": "LLM", "vision": "Vision", "asr": "ASR (Whisper)"}


def by_id(mid: str) -> dict | None:
    return next((m for m in CATALOG if m["id"] == mid), None)


def min_vram(m: dict) -> float:
    return min(m["vram"].values()) if m.get("vram") else 0.0


def fits(m: dict, free_gb: float, budget_max: float) -> str:
    """'yes' | 'offload' | 'no' relative to the VRAM budget and actually free VRAM."""
    need = min_vram(m)
    limit = min(budget_max, free_gb) if free_gb else budget_max
    if need <= limit:
        return "yes"
    if need <= limit * 2.5:
        return "offload"
    return "no"
