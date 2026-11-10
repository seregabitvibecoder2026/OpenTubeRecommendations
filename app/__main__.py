"""Entry point: `python -m app [--no-browser]`. Binds to 127.0.0.1 only."""
from __future__ import annotations

import logging
import sys
import threading
import time
import webbrowser

import uvicorn

from . import config


def main() -> None:
    no_browser = "--no-browser" in sys.argv
    url = f"http://{config.HOST}:{config.PORT}/"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print(f"\n  OpenTubeRecommendations: {url}\n  Данные: {config.data_dir()}\n  Остановить: Ctrl+C\n", flush=True)
    if not no_browser:
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
