"""Paths and default settings. Taste-related defaults are data (editable in UI), not logic."""
from __future__ import annotations

import copy
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "0.1.0"


def data_dir() -> Path:
    d = Path(os.environ.get("YNG_DATA", ROOT / "data")).expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    d = data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    d = data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


HOST = "127.0.0.1"  # never bind to anything else
PORT = int(os.environ.get("YNG_PORT", "8765"))

# Global settings (shared between profiles).
DEFAULT_SETTINGS: dict = {
    "mode": "light",  # light | medium | full
    "wizard_done": False,
    "ui_lang": "ru",
    "theme": "auto",  # auto | light | dark
    # network
    "proxy": "",  # http://host:port, socks5://host:port, socks5://127.0.0.1:9050 (Tor)
    "request_pause": 1.5,  # seconds between requests to youtube
    "max_parallel": 2,
    "retries": 3,
    "timeout": 20,
    # data sources
    "videos_per_channel": 15,
    "meta_new_per_refresh": 200,  # max new videos to fetch full metadata for in one refresh
    "listing_order": [
        {"name": "rss", "on": True},
        {"name": "ytdlp_tab", "on": True},
        {"name": "ytapi", "on": False},
    ],
    "providers": {
        "meta": [
            {"name": "watchpage", "on": True},
            {"name": "ytdlp", "on": True},
            {"name": "ytapi", "on": False},
            {"name": "altfront", "on": False},
        ],
        "subs": [
            {"name": "ytdlp", "on": True},
            {"name": "altfront", "on": False},
            {"name": "whisper", "on": False},
        ],
        "comments": [
            {"name": "ytdlp", "on": True},
            {"name": "watchpage", "on": True},
            {"name": "altfront", "on": False},
        ],
    },
    "ytdlp_clients": ["default", "tv_embedded", "web_embedded", "tv", "mweb"],
    "sub_langs": ["ru", "en"],
    "comments_max": 80,
    "comments_chars": 4000,
    "subs_chars": 20000,
    "api_key": "",
    "api_enabled": False,
    "altfront_url": "",
    "altfront_kind": "invidious",  # invidious | piped
    "cookies_browser": "",  # e.g. "firefox"; empty = off (ToS risk!)
    "auto_update_hours": 0,  # 0 = off
    # models
    "vram_budget_min": 4.0,
    "vram_budget_max": 6.0,
    "show_restricted_licenses": False,
    "embed": {"engine": "st", "model": "", "url": "http://127.0.0.1:11434", "device": "auto", "batch": 16},
    "llm": {"engine": "ollama", "url": "http://127.0.0.1:11434", "model": "", "top_n": 40, "timeout": 180,
            "llama_server_bin": "llama-server", "gguf_path": "", "ngl": 99, "ctx": 8192},
    "vision": {"engine": "ollama", "url": "http://127.0.0.1:11434", "model": "", "top_n": 60},
    "asr": {"model": "", "device": "auto", "compute_type": "auto", "max_minutes": 30},
}

DEFAULT_QUESTIONS = [
    {"key": "humor", "text": "Насколько тон видео юмористический, развлекательный?", "weight": 0.6},
    {"key": "agenda", "text": "Есть ли политическая агитация или навязывание идеологической «повестки»?", "weight": -0.8},
    {"key": "clickbait", "text": "Насколько название и превью кликбейтные по сравнению с содержанием?", "weight": -0.4},
]

DEFAULT_LLM_PROMPT = (
    "Ты помогаешь пользователю отбирать YouTube-видео для личной ленты. "
    "Оцени видео по каждому вопросу по шкале от 0 до 10 (0 — совсем нет, 10 — в полной мере). "
    "Источник может быть на русском или английском — отвечай строго JSON по схеме независимо от языка источника. "
    "Поля, помеченные как НЕДОСТУПНО, не придумывай; если данных мало, снижай confidence."
)

# Per-profile settings.
DEFAULT_PROFILE_SETTINGS: dict = {
    "weights": {"taste": 1.0, "channel": 0.8, "rules": 0.6, "fresh": 0.5, "llm": 0.7, "lang": 0.3},
    "exploration": 15,  # percent
    "fresh_half_life_days": 14,
    "max_age_days": 365,
    "min_duration_sec": 180,  # shorts threshold
    "lang_filter": "all",  # all | ru | en | sel
    "lang_selected": ["ru", "en"],
    "lang_weights": {"ru": 0.0, "en": 0.0},
    "show_18": "yes",  # yes | no | only
    "incomplete_trust": 0.7,
    "profanity_weight": 0.4,  # >0: mat is a plus
    "profanity_target": 4.0,  # matches per 1000 words that count as "full"
    "taste_min_ratings": 30,
    "logreg_min_ratings": 120,
    "feed_size": 60,
    "llm_questions": copy.deepcopy(DEFAULT_QUESTIONS),
    "llm_prompt": DEFAULT_LLM_PROMPT,
}

# Rules seeds per template: (kind, lang, pattern, weight)
PROFANITY_RU = [
    "хуй*", "хуе*", "хуё*", "хуя*", "*пизд*", "еба*", "ебал*", "ебан*", "ебл*", "ебу*", "ебёт*", "ебет*",
    "ёба*", "*заеб*", "*наеб*", "*выеб*", "*уеб*", "*отъеб*", "*съеб*", "*поеб*", "*разъеб*", "*доеб*",
    "бля", "бляд*", "блят*", "сука", "суки", "сучк*", "сучар*", "мудак*", "мудил*", "мудо*", "пидор*", "пидар*",
    "залуп*", "мандав*", "охуе*", "охуи*", "нахуй", "похуй*", "нихуя", "долбоёб*", "долбоеб*", "ебанут*",
]
PROFANITY_EN = [
    "fuck*", "*fucker*", "motherfuck*", "shit*", "bullshit*", "bitch*", "asshole*", "dickhead*", "cunt*",
    "bastard*", "wtf", "goddamn*", "damn", "dammit", "crap", "pissed", "prick*",
]

TEMPLATES: dict[str, dict] = {
    "rest": {
        "name": "Отдых",
        "color": "#e67e22",
        "icon": "🍿",
        "settings": {},
        "rules": [("stopword", "*", "#shorts", -1.0),
                  ("stoptopic", "ru", "выборы", -0.8), ("stoptopic", "en", "election", -0.8),
                  ("topic", "ru", "юмор", 0.4), ("topic", "en", "comedy", 0.4)],
    },
    "edu": {
        "name": "Образование",
        "color": "#2e86de",
        "icon": "🎓",
        "settings": {
            "weights": {"taste": 1.0, "channel": 1.0, "rules": 0.6, "fresh": 0.2, "llm": 0.8, "lang": 0.3},
            "fresh_half_life_days": 90, "max_age_days": 3650, "profanity_weight": 0.0, "min_duration_sec": 300,
            "llm_questions": [
                {"key": "edu", "text": "Насколько видео познавательное, даёт ли новые знания?", "weight": 0.9},
                {"key": "depth", "text": "Насколько глубоко и аргументированно разобрана тема?", "weight": 0.5},
                {"key": "clickbait", "text": "Насколько название кликбейтное по сравнению с содержанием?", "weight": -0.5},
            ],
        },
        "rules": [("stopword", "*", "#shorts", -1.0),
                  ("topic", "ru", "лекция", 0.4), ("topic", "en", "lecture", 0.4)],
    },
    "empty": {"name": "Пустой", "color": "#7f8c8d", "icon": "📺", "settings": {}, "rules": []},
}
COMMON_RULES = [("profanity", "ru", p, 1.0) for p in PROFANITY_RU] + [("profanity", "en", p, 1.0) for p in PROFANITY_EN]


def profile_defaults() -> dict:
    return copy.deepcopy(DEFAULT_PROFILE_SETTINGS)


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
