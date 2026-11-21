"""HTTP retrieval of public URLs supplied to the A-side tools."""

import asyncio
import socket
from contextlib import asynccontextmanager
from ipaddress import IPv6Address, ip_address
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.helpers import get_env_proxy_for_url, is_ip_address
from yarl import URL


class PublicResolver(AbstractResolver):
    def __init__(self, lookup=None):
        self.lookup = lookup

    def check(self, host, address):
        if isinstance(address, IPv6Address):
            address = address.ipv4_mapped or address
        if (
            not address.is_global
            or address.is_multicast
            or address.is_reserved
            or (isinstance(address, IPv6Address) and address.is_site_local)
        ):
            raise ValueError(f"出于安全限制，不访问本机或内网地址：{host}")

    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        lookup = self.lookup or asyncio.get_running_loop().getaddrinfo
        # Use both families, including when only one has a local interface.
        results = await lookup(
            host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
        addresses = []
        for resolved_family, _, proto, _, sockaddr in results:
            self.check(host, ip_address(sockaddr[0]))
            addresses.append(
                {
                    "hostname": host,
                    "host": sockaddr[0],
                    "port": sockaddr[1],
                    "family": resolved_family,
                    "proto": proto,
                    "flags": socket.AI_NUMERICHOST | socket.AI_NUMERICSERV,
                }
            )
        return addresses

    async def close(self):
        pass


@asynccontextmanager
async def get_public_url(url, *, resolver, timeout, headers):
    cookies = aiohttp.CookieJar()
    async with asyncio.timeout(timeout):
        for _ in range(6):
            if "@" in urlsplit(url).netloc:
                raise ValueError("HTTP 或 HTTPS 地址不能包含用户信息")
            target = URL(url)
            host = target.raw_host
            if target.scheme not in ("http", "https") or not host:
                raise ValueError("地址必须是包含主机的 HTTP 或 HTTPS URL")
            literal = is_ip_address(host)
            if literal:
                resolver.check(host, ip_address(host))
            try:
                proxy, auth = await asyncio.to_thread(get_env_proxy_for_url, target)
            except LookupError:
                proxy, auth = None, None
            if proxy is not None and not literal:
                # The proxy can resolve the target again; local DNS cannot pin its connection.
                await resolver.resolve(host, target.port)
            connector = (
                aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False)
                if proxy is None
                else None
            )
            async with aiohttp.ClientSession(
                connector=connector,
                cookie_jar=cookies,
                timeout=aiohttp.ClientTimeout(total=None),
            ) as session:
                async with session.get(
                    target,
                    headers=headers(str(target)),
                    proxy=proxy,
                    proxy_auth=auth,
                    allow_redirects=False,
                ) as response:
                    if 300 <= response.status < 400:
                        location = response.headers.get("Location")
                        if location is None:
                            raise ValueError("HTTP 重定向缺少 Location")
                        url = urljoin(str(response.url), location)
                        continue
                    yield response
                    return
        raise ValueError("HTTP 重定向超过 5 次")
