"""Safety layer: prompt-injection detection, risky-action checks, URL policy."""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

_INJECTION = [
    # English
    r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|your|system)\b.{0,30}\b(instructions?|prompts?|rules|directions|guidelines)\b",
    r"\b(new|updated|real|actual)\s+(system\s+)?instructions?\s*[:\-]",
    r"\byou\s+are\s+(now|no\s+longer)\b",
    r"\b(system|developer)\s+(prompt|message|override)\b",
    r"\bif\s+you\s+are\s+an?\s+(ai|llm|language\s+model|assistant|agent|bot)\b",
    r"\b(ai|llm)\s+(agents?|assistants?|models?)\s*(reading|that\s+read|visiting|processing)\b",
    r"\b(attention|note|important)\s*(to|for)\s*(the\s+)?(ai|llm|assistant|agent)\b",
    r"\b(send|forward|email|post|upload|transfer|share|exfiltrate)\b.{0,60}\b(passwords?|credentials|api[\s_-]?keys?|tokens?|cookies?|session|card\s+numbers?|private\s+keys?|seed\s+phrase)\b",
    r"\b(do\s+not|don't|never)\s+(tell|inform|alert|mention\s+to)\s+(the\s+)?user\b",
    r"<\|?(im_start|im_end|system|endoftext)\|?>|\[/?INST\]|<<SYS>>",
    r"^\s*(system|assistant)\s*:",
    # Russian
    r"(игнорируй|проигнорируй|забудь|отмени|не\s+обращай\s+внимания\s+на)\s.{0,40}(предыдущ|прошл|прежн|все|системн|свои).{0,30}(инструкц|указани|правил|команд|промпт)",
    r"нов(ые|ая)\s+(системн(ые|ая)\s+)?(инструкци|указани|задач)\w*\s*[:\-]",
    r"\bты\s+(теперь|больше\s+не)\b",
    r"систем(ный|ное)\s+(промпт|сообщение|указание)",
    r"если\s+ты\s+(ии|ai|нейросеть|языковая\s+модель|ассистент|агент|бот|чат-?бот)",
    r"(вниманию|для)\s+(ии|нейросет\w*|ассистент\w*|агент\w*)\b",
    r"(отправь|перешли|передай|загрузи|скинь|сообщи)\b.{0,60}(парол\w*|токен\w*|ключ\w*|cookie|куки|данные\s+карты|номер\s+карты|сид-?фраз\w*|код\w*\s+из\s+смс)",
    r"не\s+(говори|сообщай|рассказывай)\s+(об\s+этом\s+)?пользовател",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _INJECTION]


def injection_hits(text: str) -> list[str]:
    """Return the fragments of ``text`` that look like instructions to an AI."""
    hits = []
    for rx in _INJECTION_RE:
        m = rx.search(text)
        if m:
            hits.append(m.group(0).strip()[:120])
    return hits


# ---------------------------------------------------------------------------
# Risky actions
# ---------------------------------------------------------------------------

_RISKY = re.compile(
    r"(оплат|заплат|купить|куплю|покупк|оформить|заказ|в\s+корзину\s+и\s+оплат|подтверд|отправ|удали|удалени|перевест|перевод\s+средств|подписа|опубликов|разместить|снять\s+с\s+публикации|отписат|подписат|выйти\s+из\s+аккаунта|сменить\s+пароль|"
    r"\bpay\b|payment|\bbuy\b|purchase|place\s+order|\border\b|checkout|check\s+out|\bsend\b|\bsubmit\b|delete|remove|\bconfirm|transfer|withdraw|subscribe|unsubscribe|publish|\bpost\b|sign\s+(the\s+)?contract|deactivate|close\s+account|change\s+password)",
    re.IGNORECASE,
)


# Links are mostly navigation ("My orders" is not an order), so they are risky
# only when the wording is unambiguous.
_RISKY_LINK = re.compile(
    r"(оплат|заплат|купить|оформить\s+заказ|удалить|перевести\s+деньги|подписать|опубликовать|выйти\s+из\s+аккаунта|"
    r"\bpay\b|pay\s+now|\bbuy\b|checkout|place\s+order|delete|unsubscribe|sign\s+out|log\s*out)",
    re.IGNORECASE,
)


def is_risky(item: dict) -> bool:
    """A click that can send, buy, delete or publish something."""
    role = item.get("role")
    name = item.get("name", "")
    if role == "link":
        return bool(_RISKY_LINK.search(name))
    if role in ("button", "menuitem", "option", "switch"):
        return bool(_RISKY.search(name))
    return False


# ---------------------------------------------------------------------------
# URL policy
# ---------------------------------------------------------------------------


def _host_ips(host: str) -> list[ipaddress._BaseAddress]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0].split("%")[0]))
        except ValueError:
            continue
    return out


def _private(ip) -> bool:
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or ip in ipaddress.ip_network("100.64.0.0/10")
    )


def _match(host: str, pattern: str) -> bool:
    pattern = pattern.lower().lstrip(".")
    if pattern.startswith("*."):
        pattern = pattern[2:]
    return host == pattern or host.endswith("." + pattern)


@dataclass
class Policy:
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    allow_private: bool = False
    respect_robots: bool = True
    _ip_cache: dict = field(default_factory=dict, repr=False)
    _robots: dict = field(default_factory=dict, repr=False)

    def check(self, url: str) -> str | None:
        """Return a refusal reason, or None when the URL may be opened."""
        p = urllib.parse.urlsplit(url)
        if p.scheme in ("about", "data", "blob"):
            return None
        if p.scheme not in ("http", "https"):
            return f"scheme '{p.scheme}' is not allowed (only http and https)"
        host = (p.hostname or "").lower()
        if not host:
            return "URL has no host"
        for d in self.deny:
            if _match(host, d):
                return f"{host} is on the deny list"
        if self.allow and not any(_match(host, a) for a in self.allow):
            return f"{host} is not on the allow list"
        if not self.allow_private:
            if host == "localhost" or host.endswith(".localhost"):
                return f"local address {host} is blocked (enable allow_private for your own local sites)"
            if host not in self._ip_cache:
                self._ip_cache[host] = any(_private(ip) for ip in _host_ips(host))
            if self._ip_cache[host]:
                return f"{host} points to a private or internal network address (enable allow_private for your own local sites)"
        return None

    def robots_allows(self, url: str, agent: str = "Zorko") -> bool:
        if not self.respect_robots:
            return True
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("http", "https"):
            return True
        base = f"{p.scheme}://{p.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": agent})
                with urllib.request.urlopen(req, timeout=5) as r:
                    rp.parse(r.read(200_000).decode("utf-8", "replace").splitlines())
            except Exception:
                rp.parse([])  # unreachable or missing robots.txt: allow
            self._robots[base] = rp
        return rp.can_fetch(agent, url)
