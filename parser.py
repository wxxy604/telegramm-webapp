"""Парсер публичных VPN-конфигов.

Скачивает списки из SOURCES, вытаскивает ссылки vless/vmess/trojan/ss,
сохраняет их в configs.txt и запускает import_configs.py (проверка + пул Redis).

Запуск из папки vercel-bot:
    python parser.py
"""
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib import error, request
from urllib.parse import unquote

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))
import import_configs  # noqa: E402
import db  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(BASE_DIR, "configs.txt")
PREFIXES = ("vless://", "vmess://", "trojan://", "ss://")
SOURCES = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
]
TIMEOUT = 20  # секунд на скачивание одного источника
TOP_N = 10  # сколько лучших серверов показывать пользователям
PING_TRIES = 2  # замеров на сервер, берётся лучший


def fetch(url):
    """Возвращает текст источника или None, если он недоступен."""
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SupplineVPNparser/1.0)"})
    try:
        with request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except (error.URLError, OSError, ValueError) as exc:
        print("Не удалось скачать:", url, "-", exc)
        return None


def collect():
    """Собирает уникальные ссылки из всех источников."""
    seen = set()
    links = []
    for url in SOURCES:
        text = fetch(url)
        if text is None:
            continue
        found = 0
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(PREFIXES) and line not in seen:
                seen.add(line)
                links.append(line)
                found += 1
        print(f"{url}: найдено {found}")
    return links


def measure_ping(uri):
    """Возвращает пинг в миллисекундах (лучший из PING_TRIES) или None, если сервер недоступен."""
    endpoint = import_configs.parse_endpoint(uri)
    if not endpoint:
        return None
    best = None
    for _ in range(PING_TRIES):
        start = time.perf_counter()
        try:
            with socket.create_connection(endpoint, timeout=import_configs.TIMEOUT):
                ms = (time.perf_counter() - start) * 1000
        except OSError:
            continue
        best = ms if best is None else min(best, ms)
    return round(best) if best is not None else None


def server_name(uri):
    """Имя сервера из фрагмента ссылки (после #), без флагов-кодов. Если имени нет, берём адрес."""
    name = unquote(uri.split("#", 1)[1]) if "#" in uri else ""
    name = name.strip()
    return name or (import_configs.parse_endpoint(uri) or ("сервер", 0))[0]


def rank_best(links):
    """Измеряет пинг у всех живых ссылок и возвращает TOP_N лучших по пингу."""
    with ThreadPoolExecutor(max_workers=import_configs.WORKERS) as pool:
        pings = list(pool.map(measure_ping, links))
    ranked = [
        {"name": server_name(uri), "uri": uri, "ping": ping}
        for uri, ping in zip(links, pings) if ping is not None
    ]
    ranked.sort(key=lambda s: s["ping"])
    return ranked[:TOP_N]


def main():
    links = collect()
    if not links:
        raise SystemExit("Ссылки не найдены: все источники недоступны или пусты.")
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(links) + "\n")
    print("Сохранено ссылок:", len(links), "->", OUT_FILE)

    result = subprocess.run([sys.executable, os.path.join(BASE_DIR, "import_configs.py"), OUT_FILE])
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    best = rank_best(links)
    if best:
        db.save_best_servers(best)
        print(f"Сохранено лучших серверов: {len(best)}")
        for i, s in enumerate(best, 1):
            print(f"{i}. {s['name']} — {s['ping']} мс")
    else:
        print("Ни один сервер не ответил, список лучших не обновлён.")


if __name__ == "__main__":
    main()
