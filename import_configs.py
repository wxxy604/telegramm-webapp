"""Импорт VPN-конфигов в пул бота.

Использование (из папки vercel-bot):
    python import_configs.py configs.txt

В файле — по одной ссылке в строке: vless://, vmess://, trojan:// или ss://.
Парсер может просто записать свои найденные ссылки в такой файл и запустить этот скрипт.
Нужны переменные UPSTASH_REDIS_REST_URL и UPSTASH_REDIS_REST_TOKEN в файле .env.
"""
import base64
import json
import os
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))
import db  # noqa: E402

PREFIXES = ("vless://", "vmess://", "trojan://", "ss://")
TIMEOUT = 5  # секунд на проверку одного сервера
WORKERS = 20  # параллельных проверок


def parse_endpoint(uri):
    """Возвращает (host, port) из ссылки или None, если ссылку не удалось разобрать."""
    try:
        if uri.startswith("vmess://"):
            raw = uri[len("vmess://"):].strip()
            raw += "=" * (-len(raw) % 4)
            data = json.loads(base64.b64decode(raw).decode("utf-8"))
            return data["add"], int(data["port"])
        # vless, trojan, ss: host:port указаны в самом URL
        parts = urlsplit(uri)
        if parts.hostname and parts.port:
            return parts.hostname, parts.port
        # ss может быть в виде ss://base64(method:pass@host:port)
        if uri.startswith("ss://"):
            body = uri[len("ss://"):].split("#")[0]
            body += "=" * (-len(body) % 4)
            decoded = base64.b64decode(body).decode("utf-8")
            host_port = decoded.rsplit("@", 1)[1]
            host, port = host_port.rsplit(":", 1)
            return host, int(port)
    except (ValueError, KeyError, IndexError, UnicodeDecodeError, TypeError):
        return None
    return None


def is_alive(uri):
    """Проверяет, что сервер принимает TCP-соединение за TIMEOUT секунд."""
    endpoint = parse_endpoint(uri)
    if not endpoint:
        return False
    host, port = endpoint
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT):
            return True
    except OSError:
        return False


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Использование: python import_configs.py configs.txt")
    with open(sys.argv[1], encoding="utf-8") as f:
        links = list({line.strip() for line in f if line.strip().startswith(PREFIXES)})
    print("Найдено ссылок:", len(links))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(is_alive, links))
    alive = [uri for uri, ok in zip(links, results) if ok]
    print("Живых серверов:", len(alive), "из", len(links))
    print("Добавлено новых в пул:", db.add_configs(alive))


if __name__ == "__main__":
    main()
