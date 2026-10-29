"""Выдача ключей ALL VPN на лету: без БД и без пересборки ссылок.

1. GET на подписку (User-Agent Happ/1.0), ответ декодируется из Base64 в UTF-8.
2. Берутся строки vless:// как есть (их тело до '#' не меняется).
3. Для user_id выбираются 3 ключа: random.Random(user_id) даёт одинаковый результат при каждом
   запросе, поэтому у пользователя сервера не прыгают. Глобальный random не трогается.
4. Имя ключа заменяется только после первого '#'.
"""
import base64
import binascii
import random
import time
from urllib.parse import quote

import requests

SUBSCRIPTION_URL = "https://alvsub.cc"
USER_AGENT = "Happ/1.0"
NODES_PER_USER = 3
CACHE_TTL = 600  # сек: подписку не качаем на каждый запрос, но и не храним дольше 10 минут
BRAND = "🔥 MyVPN | Premium Node "

_cache = {"at": 0.0, "links": []}


def parse_links(text):
    """Base64 -> UTF-8 -> строки vless://. Если текст не Base64, берём строки как есть."""
    compact = "".join(text.split())
    try:
        padded = compact + "=" * (-len(compact) % 4)
        decoded = base64.b64decode(padded, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        decoded = text
    return [line.strip() for line in decoded.splitlines() if line.strip().startswith("vless://")]


def fetch_links():
    """Скачивает подписку (с кэшем на CACHE_TTL секунд)."""
    now = time.time()
    if _cache["links"] and now - _cache["at"] < CACHE_TTL:
        return _cache["links"]
    res = requests.get(SUBSCRIPTION_URL, headers={"User-Agent": USER_AGENT}, timeout=8)
    res.raise_for_status()
    links = parse_links(res.text)
    if not links:
        raise RuntimeError("В подписке не найдено ни одной строки vless://")
    _cache["at"] = now
    _cache["links"] = links
    return links


def rebrand(link, node_number):
    """Отрезает всё после первого '#' и ставит наше имя. Тело ссылки до '#' не меняется."""
    parts = link.split("#", 1)
    return parts[0] + "#" + quote(BRAND + str(node_number))


def pick_nodes(user_id, links):
    """3 стабильных для user_id ключа с брендовыми именами (формат, который ждёт мини приложение)."""
    rng = random.Random(int(user_id))
    chosen = rng.sample(links, min(NODES_PER_USER, len(links)))
    result = []
    for link in chosen:
        node = rng.randint(1, 999)
        result.append({"name": BRAND + str(node), "ping": 0, "uri": rebrand(link, node)})
    return result


def get_user_nodes(user_id):
    return pick_nodes(user_id, fetch_links())
