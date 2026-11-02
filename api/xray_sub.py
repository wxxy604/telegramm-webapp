"""Разбор подписок в формате Xray JSON (список конфигов, у каждого outbounds).
Превращает proxy-outbounds (vless, vmess, trojan, shadowsocks) обратно в ссылки,
которые понимает остальной парсер. Если подписка уже в виде ссылок, возвращает её как есть."""
import base64
import json
from urllib.parse import quote, urlencode

PROXY_PROTOCOLS = {"vless", "vmess", "trojan", "shadowsocks"}


def _stream_params(stream):
    """Параметры транспорта и безопасности из streamSettings в query-строку ссылки."""
    p = {}
    if not stream:
        return p
    net = stream.get("network", "tcp")
    p["type"] = net
    sec = stream.get("security", "")
    if sec:
        p["security"] = sec
    if sec == "reality":
        r = stream.get("realitySettings", {})
        p["sni"] = r.get("serverName", "")
        p["pbk"] = r.get("publicKey", "")
        p["sid"] = r.get("shortId", "")
        p["fp"] = r.get("fingerprint", "chrome")
    elif sec == "tls":
        t = stream.get("tlsSettings", {})
        p["sni"] = t.get("serverName", "")
    if net == "ws":
        ws = stream.get("wsSettings", {})
        p["path"] = ws.get("path", "/")
        if ws.get("headers", {}).get("Host"):
            p["host"] = ws["headers"]["Host"]
    if net == "grpc":
        p["serviceName"] = stream.get("grpcSettings", {}).get("serviceName", "")
    return {k: v for k, v in p.items() if v not in ("", None)}


def outbound_to_link(ob):
    """Одна outbound-запись Xray → ссылка vless:// / vmess:// / trojan:// / ss://. None если не поддерживается."""
    proto = ob.get("protocol")
    if proto not in PROXY_PROTOCOLS:
        return None
    name = quote(ob.get("tag", "") or proto)
    s = ob.get("settings", {})
    stream = ob.get("streamSettings", {})
    if proto == "vless":
        v = s["vnext"][0]
        u = v["users"][0]
        q = _stream_params(stream)
        if u.get("flow"):
            q["flow"] = u["flow"]
        return f"vless://{u['id']}@{v['address']}:{v['port']}?{urlencode(q)}#{name}"
    if proto == "vmess":
        v = s["vnext"][0]
        u = v["users"][0]
        data = {"v": "2", "ps": ob.get("tag", ""), "add": v["address"], "port": str(v["port"]),
                "id": u["id"], "aid": str(u.get("alterId", 0)), "net": stream.get("network", "tcp"),
                "tls": stream.get("security", "")}
        return "vmess://" + base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
    if proto == "trojan":
        sv = s["servers"][0]
        q = _stream_params(stream)
        return f"trojan://{quote(sv['password'])}@{sv['address']}:{sv['port']}?{urlencode(q)}#{name}"
    # shadowsocks
    sv = s["servers"][0]
    creds = base64.b64encode(f"{sv['method']}:{sv['password']}".encode()).decode()
    return f"ss://{creds}@{sv['address']}:{sv['port']}#{name}"


def links_from_subscription(text):
    """Из текста подписки возвращает список ссылок.
    Поддерживает: готовые ссылки (построчно), base64 со ссылками, Xray JSON-конфиги (список объектов с outbounds)."""
    stripped = text.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except ValueError:
            return []
        configs = data if isinstance(data, list) else [data]
        links = []
        for cfg in configs:
            for ob in cfg.get("outbounds", []) if isinstance(cfg, dict) else []:
                try:
                    link = outbound_to_link(ob)
                except (KeyError, IndexError, TypeError):
                    link = None
                if link:
                    links.append(link)
        return list(dict.fromkeys(links))
    return []
