"""Official mod metadata and task-owned downloads on the MC host."""

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

from .protocol import PRODUCT_VERSION
from .public_http import PublicResolver, get_public_url

USER_AGENT = f"mcai/{PRODUCT_VERSION}"
MODRINTH = "https://api.modrinth.com/v2"
CURSEFORGE = "https://api.curseforge.com/v1"
RETRY_DELAYS = (2, 5)
LOADERS = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}


class Downloads:
    def __init__(self, store, config, *, resolver=None):
        self.store, self.config = store, config
        self.resolver = resolver if resolver is not None else PublicResolver()

    def headers(self, url):
        headers = {"User-Agent": USER_AGENT}
        host = urlsplit(url).hostname or ""
        if url.startswith(CURSEFORGE.rstrip("/") + "/") or host.endswith(
            ".forgecdn.net"
        ):
            key = self.config.get("curseforge_api_key")
            if not key:
                raise ValueError("请在 A 插件设置中配置 CurseForge API 密钥")
            headers["x-api-key"] = key
        return headers

    async def request(self, url, params=None):
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(
                    trust_env=True, timeout=aiohttp.ClientTimeout(total=30)
                ) as session:
                    async with session.get(
                        url,
                        params=params,
                        headers=self.headers(url),
                        allow_redirects=False,
                    ) as response:
                        response.raise_for_status()
                        return await response.json()
            except (
                aiohttp.ClientConnectionError,
                asyncio.TimeoutError,
                aiohttp.ClientResponseError,
            ) as exc:
                if (
                    isinstance(exc, aiohttp.ClientResponseError)
                    and exc.status not in (408, 429)
                    and exc.status < 500
                ):
                    raise ValueError(
                        f"MOD 网站返回 HTTP {exc.status}，请核对凭据、项目或文件权限"
                    ) from exc
                if attempt == 2:
                    raise
                await asyncio.sleep(RETRY_DELAYS[attempt])

    async def mods(self, args):
        source, mode = args["source"], args["mode"]
        if source == "modrinth":
            if mode == "search":
                facets = [["project_type:mod"]]
                if args.get("game_version"):
                    facets.append(["versions:" + args["game_version"]])
                if args.get("loader"):
                    facets.append(["categories:" + args["loader"]])
                return await self.request(
                    MODRINTH + "/search",
                    {
                        "query": args["query"],
                        "facets": json.dumps(facets),
                        "offset": args.get("offset", 0),
                        "limit": 20,
                    },
                )
            project = args.get("project_id")
            if mode == "project":
                return await self.request(f"{MODRINTH}/project/{project}")
            if mode == "versions":
                params = {}
                for key, target in (
                    ("game_version", "game_versions"),
                    ("loader", "loaders"),
                ):
                    if args.get(key):
                        params[target] = json.dumps([args[key]])
                versions = await self.request(
                    f"{MODRINTH}/project/{project}/version", params
                )
                offset = args.get("offset", 0)
                return {
                    "items": versions[offset : offset + 20],
                    "next_offset": offset + 20 if offset + 20 < len(versions) else None,
                }
            version = await self.request(f"{MODRINTH}/version/{args['version_id']}")
            if mode == "file":
                return version
            if project and version["project_id"] != project:
                raise ValueError("版本不属于指定 Modrinth 项目")
            files = version["files"]
            if args.get("filename"):
                files = [item for item in files if item["filename"] == args["filename"]]
            elif len(files) > 1:
                files = [item for item in files if item.get("primary")]
            if len(files) != 1:
                raise ValueError("请明确选择要下载的 filename")
            project_info = await self.request(
                f"{MODRINTH}/project/{version['project_id']}"
            )
            file = files[0]
            return {
                "url": file["url"],
                "filename": file["filename"],
                "hashes": file["hashes"],
                "source": source,
                "project": project_info["title"],
                "project_id": version["project_id"],
                "version_id": version["id"],
                "game_versions": version["game_versions"],
                "loaders": version["loaders"],
                "dependencies": version.get("dependencies", []),
                "description": project_info.get("description", ""),
            }
        if mode == "search":
            params = {
                "gameId": 432,
                "classId": 6,
                "searchFilter": args["query"],
                "index": args.get("offset", 0),
                "pageSize": 20,
            }
            if args.get("game_version"):
                params["gameVersion"] = args["game_version"]
            if args.get("loader"):
                params["modLoaderType"] = LOADERS[args["loader"]]
            return await self.request(CURSEFORGE + "/mods/search", params)
        project = args["project_id"]
        if mode == "project":
            info = await self.request(f"{CURSEFORGE}/mods/{project}")
            info["description"] = (
                await self.request(f"{CURSEFORGE}/mods/{project}/description")
            )["data"]
            return info
        if mode == "versions":
            params = {"index": args.get("offset", 0), "pageSize": 20}
            if args.get("game_version"):
                params["gameVersion"] = args["game_version"]
            if args.get("loader"):
                params["modLoaderType"] = LOADERS[args["loader"]]
            return await self.request(f"{CURSEFORGE}/mods/{project}/files", params)
        file_id = args["file_id"]
        file = (await self.request(f"{CURSEFORGE}/mods/{project}/files/{file_id}"))[
            "data"
        ]
        if mode == "file":
            return {
                **file,
                "changelog": (
                    await self.request(
                        f"{CURSEFORGE}/mods/{project}/files/{file_id}/changelog"
                    )
                )["data"],
            }
        info = (await self.request(f"{CURSEFORGE}/mods/{project}"))["data"]
        if info.get("allowModDistribution") is False:
            raise ValueError("该 CurseForge 项目禁止第三方分发，不能自动下载")
        url = file.get("downloadUrl")
        if not url:
            url = (
                await self.request(
                    f"{CURSEFORGE}/mods/{project}/files/{file_id}/download-url"
                )
            )["data"]
        if not url:
            raise ValueError("CurseForge 未提供官方下载地址")
        return {
            "url": url,
            "filename": file["fileName"],
            "hashes": {
                ({1: "sha1", 2: "md5"}[item["algo"]]): item["value"]
                for item in file.get("hashes", [])
            },
            "source": source,
            "project": info["name"],
            "project_id": project,
            "file_id": file_id,
            "game_versions": file["gameVersions"],
            "dependencies": file.get("dependencies", []),
        }

    async def download(self, jobs, key, args):
        metadata = (
            await self.mods(args)
            if "source" in args
            else {
                "url": args["url"],
                "filename": args.get("filename", "download.bin"),
                "hashes": {"sha256": args["sha256"]} if args.get("sha256") else {},
                "source": "url",
            }
        )
        folder = self.store.directory / "downloads" / key
        folder.mkdir(parents=True, exist_ok=True)
        target, partial = folder / "content", folder / "content.part"
        if Path(metadata["filename"]).name != metadata["filename"] or any(
            char in metadata["filename"] for char in ("/", "\\", ":")
        ):
            raise ValueError("下载文件名必须是单个文件名")
        for attempt in range(3):
            if jobs.stopped(key):
                return
            try:
                async with get_public_url(
                    metadata["url"],
                    resolver=self.resolver,
                    timeout=600,
                    headers=self.headers,
                ) as response:
                    response.raise_for_status()
                    hashes = {
                        name: hashlib.new(name)
                        for name in {"sha256", *metadata["hashes"]}
                    }
                    size = 0
                    reported_at = 0
                    with partial.open("wb") as output:
                        async for chunk in response.content.iter_chunked(262144):
                            if jobs.stopped(key):
                                return
                            size += len(chunk)
                            if size > self.config.get(
                                "download_max_bytes", 2 * 1024**3
                            ):
                                raise ValueError("下载超过 download_max_bytes 限制")
                            output.write(chunk)
                            for hasher in hashes.values():
                                hasher.update(chunk)
                            if time.monotonic() - reported_at >= 0.5:
                                jobs.update(
                                    key,
                                    progress={"bytes": size, "attempt": attempt + 1},
                                )
                                reported_at = time.monotonic()
                for name, expected in metadata["hashes"].items():
                    if hashes[name].hexdigest().lower() != expected.lower():
                        raise ValueError(f"下载 {name} 校验不匹配，文件未安装")
                os.replace(partial, target)
                jobs.update(key, progress={"bytes": size, "attempt": attempt + 1})
                record = {
                    **metadata,
                    "id": key,
                    "task_id": jobs.get(key)["task_id"],
                    "instance": jobs.get(key)["instance"],
                    "size": size,
                    "sha256": hashes["sha256"].hexdigest(),
                    "completed_at": time.time(),
                }
                self.store.save("download", key, record)
                jobs.emit(key, record)
                return
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if (
                    isinstance(exc, aiohttp.ClientResponseError)
                    and exc.status not in (408, 429)
                    and exc.status < 500
                ):
                    raise ValueError(
                        f"下载返回 HTTP {exc.status}，请核对来源与凭据"
                    ) from exc
                if attempt == 2:
                    raise
                await asyncio.sleep(RETRY_DELAYS[attempt])

    async def verify(self, key, instance, task):
        record = self.store.get("download", key)
        if (
            record is None
            or record["instance"] != instance
            or record["task_id"] != task
        ):
            raise ValueError("下载未完成或不属于当前实例和任务")
        path = self.store.directory / "downloads" / key / "content"
        with path.open("rb") as stream:
            actual = (
                await asyncio.to_thread(hashlib.file_digest, stream, "sha256")
            ).hexdigest()
        if actual != record["sha256"]:
            raise ValueError("暂存下载已变化，请重新下载并提案")
        return record, path
