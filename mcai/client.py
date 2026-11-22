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


FILE_TRANSFER_TIMEOUT = aiohttp.ClientTimeout(
    total=None, connect=35, sock_connect=35, sock_read=35
)


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
        self,
        method,
        path,
        *,
        stopped=None,
        data_factory=None,
        once=False,
        sink=None,
        **kwargs,
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
                    if (
                        path.split("?")[0]
                        in ("/instances", "/configuration", "/storage/cleanup")
                        or path.startswith("/management/")
                        or method == "POST"
                        and path.startswith("/operations/")
                        or path.endswith("?release=1")
                    ) and response.headers.get("X-MCAI-Protocol") != PROTOCOL:
                        raise RemoteError(
                            "A/B 产品协议不匹配或 B 未提供协议标识，请配套更新后再执行"
                        )
                    if delay > 0.5:
                        logger.info("与 MC 控制程序的连接已恢复")
                    if sink is not None:
                        async for chunk in response.content.iter_chunked(262144):
                            await asyncio.to_thread(sink.write, chunk)
                        sink.seek(0)
                        return None
                    return await response.json()
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
        release_checkpoint=None,
        record_release=None,
    ):
        operation_id = operation_id or uuid.uuid4().hex
        body = {
            "instance": instance,
            "action": action,
            "arguments": arguments or {},
            "task_id": task_id,
        }
        cancel_sent = False
        path = f"/operations/{operation_id}"

        async def original_release(checkpoint):
            reply = await self.request("GET", path + "?release=1")
            if (
                not isinstance(reply, dict)
                or not reply.get("operation_store")
                or "operation" not in reply
                or checkpoint.get("store")
                and reply["operation_store"] != checkpoint["store"]
            ):
                raise RemoteError("无法确认原 B 操作库，未补交")
            original = reply["operation"]
            if original is not None and (
                original.get("id") != operation_id
                or any(original.get(field) != value for field, value in body.items())
            ):
                raise RemoteError("原操作编号或参数不匹配，未补交")
            return original

        try:
            if before_release is None:
                await self.request("GET", "/instances", stopped=stopped)
                operation = await self.request("POST", path, json=body, stopped=stopped)
            else:
                checkpoint = release_checkpoint
                operation = await original_release(checkpoint) if checkpoint else None
                if operation is None:
                    if checkpoint:
                        if (
                            checkpoint["state"] != "prepared"
                            or not checkpoint.get("store")
                            or checkpoint["body"] != body
                        ):
                            raise RemoteError("原操作记录不可核实，未补交")
                    else:
                        origin = await self.request(
                            "GET", "/instances?operation_store=1", stopped=stopped
                        )
                        checkpoint = {
                            "state": "prepared",
                            "store": origin["operation_store"],
                            "body": body,
                        }
                    if stopped and stopped():
                        raise SubmissionCancelled
                    before_release()
                    record_release(checkpoint)
                    try:
                        operation = await self.request(
                            "POST",
                            path,
                            params={"operation_store": checkpoint["store"]},
                            json=body,
                            stopped=stopped,
                            once=True,
                        )
                    except (aiohttp.ClientError, asyncio.TimeoutError):
                        operation = await original_release(checkpoint)
                        if operation is None:
                            raise RemoteError("原操作当前未受理，请续接后核对原编号")
                record_release({**checkpoint, "state": "accepted"})
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
            timeout=FILE_TRANSFER_TIMEOUT,
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
                        timeout=FILE_TRANSFER_TIMEOUT,
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
