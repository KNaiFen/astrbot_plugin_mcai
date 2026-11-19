import asyncio
import json
import logging
import uuid
from urllib.parse import urlsplit

import aiohttp

from .protocol import HEADERS, PROTOCOL

logger = logging.getLogger(__name__)


class RemoteError(RuntimeError):
    def __init__(self, message, *, operation=None):
        super().__init__(message)
        self.operation = operation


class SubmissionCancelled(Exception):
    pass


class ReleaseDeferred(Exception):
    """Administrator feedback changed before the first send."""


class HostClient:
    def __init__(self, url, token, fingerprint=""):
        self.url = url.rstrip("/")
        if urlsplit(self.url).scheme != "https":
            raise ValueError("host_url 必须使用 https://")
        self.token = token
        self.fingerprint = "".join(fingerprint.replace(":", "").split()).lower()
        if fingerprint.strip():
            try:
                digest = bytes.fromhex(self.fingerprint)
            except ValueError as exc:
                raise ValueError(
                    "host_fingerprint 必须为 64 位 SHA-256 十六进制指纹"
                ) from exc
            if len(digest) != 32:
                raise ValueError("host_fingerprint 必须为 64 位 SHA-256 十六进制指纹")
        self.ssl = aiohttp.Fingerprint(digest) if self.fingerprint else True
        self.session = None

    async def close(self):
        if self.session:
            await self.session.close()

    async def request(
        self, method, path, *, stopped=None, data_factory=None, once=False, **kwargs
    ):
        if self.session is None:
            self.session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.token}", **HEADERS},
                timeout=aiohttp.ClientTimeout(total=35),
                connector=aiohttp.TCPConnector(ssl=self.ssl),
            )
        delay = 0.5
        while True:
            if stopped and stopped():
                raise SubmissionCancelled
            stream = data_factory() if data_factory else None
            try:
                async with self.session.request(
                    method,
                    self.url + path,
                    allow_redirects=False,
                    **({**kwargs, "data": stream} if data_factory else kwargs),
                ) as response:
                    if response.status in (502, 503, 504):
                        raise aiohttp.ClientConnectionError(f"HTTP {response.status}")
                    if 300 <= response.status < 400:
                        raise RemoteError(
                            "控制地址发生重定向，请将 host_url 设置为最终 HTTPS 地址"
                        )
                    if response.status >= 400:
                        raw = await response.text()
                        try:
                            error = json.loads(raw).get("error", raw)
                        except ValueError:
                            error = raw
                        raise RemoteError(f"HTTP {response.status}: {error}")
                    result = await response.json()
                    if (
                        path.split("?")[0] in ("/instances", "/configuration")
                        or method == "POST"
                        and path.startswith("/operations/")
                    ) and response.headers.get("X-MCAI-Protocol") != PROTOCOL:
                        raise RemoteError(
                            "A/B 产品协议不匹配或 B 未提供协议标识，请配套更新后再执行"
                        )
                    if delay > 0.5:
                        logger.info("与 MC 控制程序的连接已恢复")
                    return result
            except aiohttp.ServerFingerprintMismatch as exc:
                raise RemoteError(
                    "服务端证书指纹不匹配，请核对 B 显示的指纹与 host_fingerprint"
                ) from exc
            except aiohttp.ClientSSLError as exc:
                raise RemoteError(
                    "HTTPS 证书校验失败，请检查 host_fingerprint 和控制地址"
                ) from exc
            except (aiohttp.ContentTypeError, json.JSONDecodeError) as exc:
                raise RemoteError(f"控制程序返回了无效 JSON 数据：{exc}") from exc
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if once:
                    raise
                logger.warning("连接中断，%.1f 秒后重连：%s", delay, exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 10)
            finally:
                if stream is not None:
                    stream.close()

    async def call(
        self,
        instance,
        action,
        arguments=None,
        *,
        operation_id=None,
        task_id="manual",
        stopped=None,
        before_release=None,
        release_submitted=False,
    ):
        operation_id = operation_id or uuid.uuid4().hex
        body = {
            "instance": instance,
            "action": action,
            "arguments": arguments or {},
            "task_id": task_id,
        }
        cancel_sent = False
        try:
            path = f"/operations/{operation_id}"
            if release_submitted:
                operation = await self.request("GET", path)
            else:
                await self.request("GET", "/instances", stopped=stopped)
                if before_release:
                    before_release()
                try:
                    operation = await self.request(
                        "POST",
                        path,
                        json=body,
                        stopped=stopped,
                        once=before_release is not None,
                    )
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    operation = await self.request("GET", path)
        except SubmissionCancelled:
            operation = await self.request("POST", f"/operations/{operation_id}/cancel")
            cancel_sent = True
        while operation["status"] in ("pending", "running"):
            if stopped and stopped() and not cancel_sent:
                operation = await self.request(
                    "POST", f"/operations/{operation_id}/cancel"
                )
                cancel_sent = True
            await asyncio.sleep(0.3)
            try:
                operation = await self.request(
                    "GET",
                    f"/operations/{operation_id}",
                    stopped=stopped if not cancel_sent else None,
                )
            except SubmissionCancelled:
                operation = await self.request(
                    "POST", f"/operations/{operation_id}/cancel"
                )
                cancel_sent = True
        if operation["status"] == "failed":
            raise RemoteError(operation["error"], operation=operation)
        return operation["result"]

    async def import_download(self, record, path):
        key = record["id"]
        await self.request("POST", f"/downloads/{key}", json=record)
        await self.request(
            "PUT",
            f"/downloads/{key}/content",
            data_factory=lambda: open(path, "rb"),
            headers={"Content-Type": "application/octet-stream"},
            timeout=aiohttp.ClientTimeout(
                total=None, connect=35, sock_connect=35, sock_read=35
            ),
        )

    async def download_instance_file(self, instance, path, destination, operation_id):
        if self.session is None:
            await self.request("GET", "/instances")
        temporary = destination.with_name(operation_id + ".part")
        try:
            for attempt in range(2):
                try:
                    async with self.session.get(
                        f"{self.url}/instances/{instance}/files",
                        params={"path": path},
                        allow_redirects=False,
                    ) as response:
                        if response.headers.get("X-MCAI-Protocol") != PROTOCOL:
                            raise RemoteError("A/B 产品协议不匹配")
                        if response.status >= 400:
                            raise RemoteError(
                                f"HTTP {response.status}: {await response.text()}"
                            )
                        size = 0
                        with temporary.open("wb") as output:
                            async for chunk in response.content.iter_chunked(262144):
                                output.write(chunk)
                                size += len(chunk)
                    temporary.replace(destination)
                    return size
                except (aiohttp.ServerFingerprintMismatch, aiohttp.ClientSSLError):
                    raise
                except (
                    aiohttp.ClientConnectionError,
                    aiohttp.ClientPayloadError,
                    asyncio.TimeoutError,
                ):
                    if attempt:
                        raise
                    logger.warning("拉取 B 端文件时连接中断，0.5 秒后从头重传")
                    await asyncio.sleep(0.5)
        finally:
            temporary.unlink(missing_ok=True)
