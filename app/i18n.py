"""UI strings. Templates call t('key'); add a new dict to localize."""
from __future__ import annotations

RU = {
    "app.title": "OpenTubeRecommendations",
    "nav.feed": "Лента", "nav.channels": "Каналы", "nav.rules": "Правила и вкус", "nav.jobs": "Задачи",
    "nav.models": "Модели", "nav.settings": "Настройки", "nav.profiles": "Профили",
    "hdr.profile": "Профиль", "hdr.jobs_running": "задач идёт", "hdr.no_jobs": "задач нет",
    "hdr.mode": "Режим", "mode.light": "Лёгкий", "mode.medium": "Средний", "mode.full": "Полный",
    "hdr.emb": "эмбеддинги", "hdr.llm": "LLM", "hdr.none": "нет",
    # feed
    "feed.empty": "Лента пуста. Добавьте каналы и нажмите «Обновить ленту».",
    "feed.refresh": "Обновить ленту", "feed.lang": "Язык", "feed.lang.all": "все", "feed.lang.ru": "только ru",
    "feed.lang.en": "только en", "feed.lang.sel": "выбранные", "feed.18": "18+", "feed.18.yes": "показывать",
    "feed.18.no": "скрыть", "feed.18.only": "только 18+", "feed.similar": "Похожие на", "feed.back": "← вся лента",
    "feed.stats": "кандидатов {candidates}, оценок {n_rated}, вкус: {taste_mode}, {ms} мс",
    "card.like": "Нравится", "card.dislike": "Не нравится", "card.hide_channel": "Скрыть канал",
    "card.more": "Ещё такое", "card.why": "почему тут", "card.details": "подробнее", "card.incomplete": "неполные данные",
    "card.explore": "исследование", "card.mat": "мат", "card.opened": "открыто",
    # channels
    "ch.add": "Добавить каналы", "ch.add.hint": "Ссылки на каналы или видео, @хэндлы, UC-идентификаторы — по одному в строке или через пробел.",
    "ch.import": "Импорт subscriptions.csv (Google Takeout)", "ch.weight": "Вес", "ch.pause": "Пауза", "ch.resume": "Вкл.",
    "ch.remove": "Убрать", "ch.hidden": "скрыт", "ch.videos": "видео", "ch.last": "обновлён", "ch.err": "ошибка",
    "ch.candidates": "Кандидаты (новые каналы)", "ch.accept": "Принять", "ch.reject": "Отклонить",
    "ch.discover": "Искать новые каналы", "ch.discover.search": "+ поиск по темам лайков (yt-dlp, редко)",
    "ch.discover.llm": "+ подсказки LLM", "ch.none": "Каналов пока нет.", "ch.unhide": "Показать",
    "ch.update_one": "Обновить",
    # rules
    "rules.weights": "Веса факторов", "rules.w.taste": "Вкус (по оценкам)", "rules.w.channel": "Вес и приор канала",
    "rules.w.rules": "Правила (темы, мат)", "rules.w.fresh": "Свежесть", "rules.w.llm": "LLM-оценки", "rules.w.lang": "Язык",
    "rules.feed": "Лента", "rules.exploration": "Исследование, % ленты", "rules.half_life": "Затухание свежести (период полураспада, дней)",
    "rules.max_age": "Не старше, дней", "rules.min_dur": "Порог шортсов (сек.)", "rules.feed_size": "Размер ленты",
    "rules.trust": "Доверие к неполным данным", "rules.prof_w": "Мат: вес (+ нравится / − не нравится)",
    "rules.prof_target": "Мат: «полная» плотность (на 1000 слов)", "rules.lang_w": "Вес языка",
    "rules.taste_min": "Оценок до полной силы вкуса", "rules.logreg_min": "Оценок для логрегрессии",
    "rules.lists": "Словари и темы", "rules.stopword": "Стоп-слова (видео скрывается)",
    "rules.stoptopic": "Стоп-темы (штраф; «тема: вес»)", "rules.topic": "Темы (бонус/штраф; «тема: вес»)",
    "rules.profanity": "Словарь мата (шаблоны, * — любые буквы)", "rules.lists.hint": "По одной записи в строке. Язык: * — для всех.",
    "rules.questions": "LLM-вопросы", "rules.q.key": "ключ", "rules.q.text": "вопрос", "rules.q.weight": "вес (−1…1)",
    "rules.q.prompt": "Системный промпт", "rules.q.hint": "Ответ модели — 0…10 по каждому вопросу; вклад = вес × оценка/10.",
    "save": "Сохранить", "add": "Добавить", "delete": "Удалить", "cancel": "Отмена", "start": "Запустить", "stop": "Стоп",
    # jobs
    "jobs.title": "Задачи", "jobs.hint": "Ничего тяжёлого не запускается само. Каждая задача — по кнопке, с прогрессом и «Стоп».",
    "jobs.n": "сколько видео", "jobs.recent": "Последние задачи", "jobs.log": "лог",
    "jobs.status.running": "идёт", "jobs.status.done": "готово", "jobs.status.error": "ошибка",
    "jobs.status.stopped": "остановлено", "jobs.status.interrupted": "прервано",
    # models
    "models.title": "Модели", "models.hint": "Приложение полностью работает без моделей (режим «Лёгкий»). Скачивание — только по кнопке.",
    "models.gpu": "Видеокарта", "models.nogpu": "GPU не найден — модели будут работать на CPU (медленно) или через Ollama.",
    "models.budget": "Бюджет VRAM, ГБ", "models.restricted": "показать и с ограниченной лицензией",
    "models.kind": "Тип", "models.all": "все", "models.disk": "Диск", "models.vram": "VRAM", "models.langs": "Языки",
    "models.license": "Лицензия", "models.fits": "Влезет", "models.fits.yes": "да", "models.fits.offload": "оффлоад",
    "models.fits.no": "нет", "models.download": "Скачать", "models.use": "Использовать", "models.in_use": "используется",
    "models.test": "Тест", "models.installed": "скачана", "models.custom": "Своя модель",
    "models.custom.hint": "HF ID (sentence-transformers / faster-whisper), тег Ollama или HF-репозиторий с GGUF.",
    "models.engine": "Движок", "models.over_budget": "Больше бюджета VRAM: возможен частичный оффлоад в RAM, будет медленнее. Скачать?",
    "models.extras": "Python-пакеты", "models.install": "Установить",
    "models.ollama": "Ollama", "models.ollama.down": "не отвечает", "models.ollama.up": "работает",
    "models.gguf.files": "Показать файлы", "models.llama": "llama.cpp (llama-server)",
    # settings
    "set.title": "Настройки", "set.net": "Сеть", "set.proxy": "Прокси (http://…, socks5://…, Tor: socks5://127.0.0.1:9050)",
    "set.pause": "Пауза между запросами, с", "set.parallel": "Параллельных запросов", "set.retries": "Повторов при ошибке",
    "set.sources": "Источники данных (порядок — сверху вниз)", "set.sub_langs": "Языки субтитров (через пробел)",
    "set.per_channel": "Видео на канал при обновлении", "set.comments_max": "Комментариев на видео",
    "set.api": "YouTube Data API (свой ключ, внешний сервис)", "set.api_on": "Включить API",
    "set.alt": "Альтернативный фронтенд (Invidious/Piped)", "set.alt.warn": "Инстанс видит ваши запросы и бывает нестабилен.",
    "set.cookies": "Куки браузера для yt-dlp", "set.cookies.warn": "Нарушает ToS YouTube и связывает запросы с вашим аккаунтом. По умолчанию выключено.",
    "set.clients": "Клиенты yt-dlp (player_client) по порядку", "set.auto": "Автообновление, часов (0 — выкл.)",
    "set.data": "Папка данных", "set.theme": "Тема", "set.theme.auto": "как в системе", "set.theme.light": "светлая",
    "set.theme.dark": "тёмная",
    # profiles
    "prof.title": "Профили", "prof.create": "Создать", "prof.template": "Шаблон", "prof.dup": "Дублировать",
    "prof.dup.hist": "с историей оценок", "prof.rename": "Переименовать", "prof.delete": "Удалить", "prof.reset": "Сбросить оценки",
    "prof.export": "Экспорт", "prof.export.hist": "включить историю оценок", "prof.import": "Импорт профиля (JSON)",
    "prof.import.new": "как новый профиль", "prof.import.replace": "заменить профиль с тем же UUID",
    "prof.reset_all": "Сбросить всё (удалить все данные)", "prof.active": "активный", "prof.switch": "Сделать активным",
    "prof.confirm": "Точно?",
    # wizard
    "wiz.title": "Первый запуск", "wiz.mode": "Режим работы",
    "wiz.light": "Без нейросетей: правила, веса каналов, TF-IDF. Ноль скачиваний.",
    "wiz.medium": "+ маленькая эмбеддинг-модель (0.5–2 ГБ). Лучше понимает смысл.",
    "wiz.full": "+ LLM на выбор (и при желании vision). Оценки по вашим вопросам.",
    "wiz.profile": "Первый профиль", "wiz.go": "Начать", "wiz.later": "Всё можно поменять позже.",
    # video
    "vid.evidence": "Какие данные есть", "vid.probe": "Проверить источники для этого видео", "vid.llm": "Оценки LLM",
    "vid.why": "Почему тут", "vid.conf": "полнота данных",
    "ev.meta": "метаданные", "ev.description": "описание", "ev.comments": "комментарии", "ev.subtitles": "субтитры",
    "ev.thumbnail": "эскиз (vision)", "ev.channel_prior": "приор канала",
}

LANGS = {"ru": RU}


def t(key: str, lang: str = "ru", **kw) -> str:
    s = LANGS.get(lang, RU).get(key) or RU.get(key) or key
    return s.format(**kw) if kw else s
