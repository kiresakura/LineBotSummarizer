"""SSRF-safe HTTP 取得工具。

對所有「使用者提供之 URL」發出的請求（網頁爬取、字幕下載、媒體下載）都應走這裡：

1. scheme 白名單（僅 http/https）、拒絕內嵌帳密的 URL
2. 解析 DNS 後封鎖私有 / loopback / link-local / 保留 / 雲端 metadata 等非公開位址
3. 關閉自動重導，改為手動逐跳重新驗證（防止「公開 URL → 內網」的重導繞過）
4. 串流下載並限制回應大小（防記憶體 DoS）
5. 全域 semaphore 限制同時對外請求數（避免被當成放大器）

注意：每次請求前解析 DNS 並驗證 IP，可擋下絕大多數 SSRF 向量。DNS rebinding 仍有
殘餘風險，正式環境建議搭配網路層 egress 政策作為縱深防禦。
"""

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https"}
DEFAULT_MAX_BYTES = 8 * 1024 * 1024  # 8 MB
DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_REDIRECTS = 5
_REDIRECT_CODES = {301, 302, 303, 307, 308}

# 限制同時對外請求數，避免大量訊息湧入時把伺服器當成放大器
_OUTBOUND = asyncio.Semaphore(10)


class UnsafeURLError(Exception):
    """目標 URL 指向不允許 / 非公開位址，或回應違反限制時拋出。"""


class SafeResponse:
    """精簡的回應容器（已完成大小檢查與讀取）。"""

    def __init__(
        self, url: str, status_code: int, headers: httpx.Headers, content: bytes
    ):
        self.url = url
        self.status_code = status_code
        self.headers = headers
        self.content = content

    @property
    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.content.decode(charset, errors="replace")
        except (LookupError, TypeError):
            return self.content.decode("utf-8", errors="replace")


def _ip_is_public(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _check_url_sync(url: str) -> str:
    """同步檢查 scheme / 帳密 / 字面 IP，回傳待解析的 hostname。"""
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"不允許的 scheme: {parts.scheme!r}")
    if parts.username or parts.password:
        raise UnsafeURLError("不允許帶有帳密的 URL")
    host = parts.hostname
    if not host:
        raise UnsafeURLError("URL 缺少主機名")
    # 若 host 本身就是字面 IP，立即驗證
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass  # 非字面 IP，留待 DNS 解析階段
    else:
        if not _ip_is_public(host):
            raise UnsafeURLError(f"目標為非公開位址: {host}")
    return host


def _resolve_and_check(host: str) -> None:
    """解析 host 的所有 IP，任一為非公開位址即拒絕。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeURLError(f"DNS 解析失敗 {host}: {e}") from e
    ips = {info[4][0] for info in infos}
    if not ips:
        raise UnsafeURLError(f"{host} 無法解析到任何位址")
    for ip in ips:
        if not _ip_is_public(ip):
            raise UnsafeURLError(f"{host} 解析到非公開位址 {ip}")


async def _ensure_safe(url: str) -> None:
    host = _check_url_sync(url)
    loop = asyncio.get_event_loop()
    # getaddrinfo 是 blocking call，丟到 executor 避免卡住事件迴圈
    await loop.run_in_executor(None, _resolve_and_check, host)


async def safe_get(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict | None = None,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
) -> SafeResponse:
    """SSRF-safe 的 GET：逐跳驗證重導、串流並限制回應大小。

    可能拋出 UnsafeURLError（不安全 / 超量）或 httpx.HTTPStatusError（4xx/5xx）。
    """
    request_headers = headers or {}
    current = url
    async with (
        _OUTBOUND,
        httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client,
    ):
        for _ in range(max_redirects + 1):
            await _ensure_safe(current)
            async with client.stream("GET", current, headers=request_headers) as resp:
                if resp.status_code in _REDIRECT_CODES:
                    loc = resp.headers.get("location")
                    if not loc:
                        raise UnsafeURLError("收到重導但缺少 Location")
                    current = str(httpx.URL(current).join(loc))
                    continue

                resp.raise_for_status()

                cl = resp.headers.get("content-length")
                if cl and cl.isdigit() and int(cl) > max_bytes:
                    raise UnsafeURLError(f"回應過大: {cl} bytes（上限 {max_bytes}）")

                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise UnsafeURLError(f"回應超過大小上限 {max_bytes} bytes")
                return SafeResponse(
                    str(resp.url), resp.status_code, resp.headers, bytes(buf)
                )

    raise UnsafeURLError("重導次數過多")
