"""Сбалансированный пакет из 3 конфигураций для пользователя.

Логика та же, что в vercel-bot/get_balanced_pack.py: уникальные host:port, случайные 3 сервера,
ссылки vless:// с брендированными именами Node A/B/C. Модуль лежит в api/, потому что Vercel
деплоит только эту папку.
"""
import base64
import random
from urllib.parse import quote

PACK_SIZE = 3
NODE_NAMES = ["Node A", "Node B", "Node C"]
DEFAULT_FP = "chrome"


def unique_servers(servers):
    """Оставляет по одной записи на пару host:port."""
    unique = {}
    for s in servers:
        unique.setdefault((s["host"], s["port"]), s)
    return list(unique.values())


def build_link(server, node_name):
    """vless:// ссылка по шаблону с брендированным именем."""
    name = quote(f"🔥 MyVPN | {node_name}")
    return (
        f"vless://{server['uuid']}@{server['host']}:{server['port']}"
        f"?encryption=none&flow={server.get('flow', '')}&type=tcp&security=reality"
        f"&sni={server.get('sni', '')}&fp={server.get('fp', DEFAULT_FP)}"
        f"&pbk={server.get('pbk', '')}&sid={server.get('sid', '')}#{name}"
    )


def make_pack(servers):
    """Случайно выбирает PACK_SIZE разных серверов и возвращает их как dict-записи."""
    unique = unique_servers(servers)
    if len(unique) < PACK_SIZE:
        raise ValueError(f"Уникальных серверов {len(unique)}, нужно {PACK_SIZE}.")
    return random.sample(unique, PACK_SIZE)


def pack_links(chosen):
    """Ссылки vless:// для выбранных серверов."""
    return [build_link(s, NODE_NAMES[i]) for i, s in enumerate(chosen)]


def to_base64(links):
    return base64.b64encode("\n".join(links).encode("utf-8")).decode("ascii")
