"""Pinned Java tools for A-side task workspaces."""

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

import aiohttp

from .jobs import terminate_tree
from .public_http import PublicResolver, get_public_url

HERE = Path(__file__).parent
VENDOR = HERE / "vendor/workspace"
SOURCE = HERE / "java/WorkspaceTool.java"
MAVEN = "https://repo.maven.apache.org/maven2/"
DEPENDENCIES = {
    "org/vineflower/vineflower/1.12.0/vineflower-1.12.0": "1dfcfe974395734fa467ce620661c7623d05ba83670de0529b1fbd63ff548b9d",
    "net/fabricmc/mapping-io/0.9.2/mapping-io-0.9.2": "da2195f6c85463c7ece951fffb211c7ffda8d2d29cf2a887fe76bcc4f1a2c5ec",
    "org/ow2/asm/asm/9.11.1/asm-9.11.1": "ae4e6e10d59d0a1500317764b21881ad883f8550e33c66e6142f7032c6fb566c",
    "org/ow2/asm/asm-tree/9.11.1/asm-tree-9.11.1": "2b15c3c1b288a9fad3bb2cd6d988ba9521554914ed1f2a2029141fa3f483154a",
    "org/ow2/asm/asm-commons/9.11.1/asm-commons-9.11.1": "6a5095ec53726156a78b2cd2efd45bc4e877754eca7c234f61224a53d6bfa661",
    "org/ow2/asm/asm-util/9.11.1/asm-util-9.11.1": "23fdffacdfc38f447cbd8b80e058f462451fa5d4709e437067d530fa6513579d",
}
JDK_TOOLS = ("java", "javac", "javap", "jar")


def jdk_executables(configured_path="", *, required=JDK_TOOLS):
    suffix = ".exe" if os.name == "nt" else ""
    candidates = []
    if configured_path:
        selected = Path(configured_path).expanduser()
        if selected.is_file() and selected.name.lower() in {
            name + suffix for name in JDK_TOOLS
        }:
            candidates.append(selected.resolve().parent)
    else:
        if home := os.environ.get("JAVA_HOME"):
            candidates.append((Path(home) / "bin").resolve())
        for name in ("java", "javap", "javac"):
            if found := shutil.which(name):
                candidate = Path(found).resolve()
                candidates.append(candidate.parent)
                if name == "java" and "javapath" in candidate.parent.name.lower():
                    # Oracle's PATH launcher lacks the other JDK executables.
                    result = subprocess.run(
                        [candidate, "-XshowSettings:properties", "-version"],
                        capture_output=True,
                        timeout=10,
                        check=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if match := re.search(
                        rb"(?m)^\s*java\.home = (.+)\r?$", result.stderr
                    ):
                        home = os.fsdecode(match[1].rstrip())
                        candidates.append((Path(home) / "bin").resolve())
    for bin_dir in candidates:
        paths = {name: (bin_dir / (name + suffix)).resolve() for name in required}
        if all(path.parent == bin_dir and path.is_file() for path in paths.values()):
            return paths
    names = "、".join(name + suffix for name in required)
    raise ValueError(
        f"A 端找不到同一 bin 目录中含 {names} 的 JDK，请配置 workspace_java_path 或设置 A 端 JAVA_HOME / PATH"
    )


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def classpath(paths):
    return os.pathsep.join(map(str, paths))


def check_dependency(path, expected):
    if sha256(path) != expected:
        raise ValueError(f"A 端工作区工具 SHA-256 不匹配：{path}，请移除后重新准备")
    return path


async def run_java_tool(command, process_job, timeout, label, *, limit=2 * 1024**2):
    prefix = []
    if process_job is not None:
        prefix = [
            sys._base_executable,
            str(HERE / "workspace_worker.py"),
            process_job,
        ]
    process = await asyncio.create_subprocess_exec(
        *prefix,
        *map(str, command),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output, tail, truncated = bytearray(), bytearray(), False
    try:
        async with asyncio.timeout(timeout):
            while data := await process.stdout.read(8192):
                room = limit - len(output)
                output.extend(data[:room])
                tail = (tail + data)[-2000:]
                truncated |= len(data) > room
            code = await process.wait()
    except TimeoutError:
        raise TimeoutError(f"{label} 超过 {timeout} 秒，已结束进程树") from None
    finally:
        if process.returncode is None:
            # Drain the pipe while waiting for the terminated process tree.
            await asyncio.gather(terminate_tree(process), process.stdout.read())
    if code:
        raise ValueError(
            f"{label} 退出码 {code}：{tail.decode('utf-8', 'replace').strip()}"
        )
    return output.decode("utf-8", "replace"), truncated


class WorkspaceTools:
    def __init__(self, cache, process_job, *, vendor=VENDOR):
        self.cache = Path(cache)
        self.vendor = vendor
        self.process_job = process_job
        self.lock = asyncio.Lock()

    def local_dependency(self, coordinate):
        filename = coordinate.rsplit("/", 1)[-1] + ".jar"
        for directory in (self.vendor, self.cache):
            path = directory / filename
            if path.is_file():
                return check_dependency(path, DEPENDENCIES[coordinate])

    async def download(self, coordinate):
        self.cache.mkdir(parents=True, exist_ok=True)
        filename = coordinate.rsplit("/", 1)[-1] + ".jar"
        with NamedTemporaryFile(dir=self.cache, suffix=".part", delete=False) as stream:
            partial = Path(stream.name)
            try:
                size = 0
                async with get_public_url(
                    MAVEN + coordinate + ".jar",
                    resolver=PublicResolver(),
                    timeout=60,
                    headers=lambda _: {},
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > 16 * 1024**2:
                            raise ValueError(
                                f"A 端工作区工具下载超过 16 MiB：{filename}"
                            )
                        stream.write(chunk)
                stream.close()
                check_dependency(partial, DEPENDENCIES[coordinate])
                return partial.replace(self.cache / filename)
            except (aiohttp.ClientError, OSError, TimeoutError) as error:
                raise ValueError(
                    f"A 端无法下载工作区工具 {filename}：{error}。"
                    "请在源码仓库运行 scripts/setup_workspace_tools.py 预置工具，或允许 A 端通过代理下载"
                ) from error
            finally:
                stream.close()
                partial.unlink(missing_ok=True)

    async def prepare(self, jdk, *, helper=True):
        async with self.lock:
            jars = [
                self.local_dependency(coordinate) or await self.download(coordinate)
                for coordinate in DEPENDENCIES
            ]
            if not helper:
                return jars, None
            key = hashlib.sha256(
                bytes.fromhex(sha256(SOURCE))
                + b"".join(
                    bytes.fromhex(checksum) for checksum in DEPENDENCIES.values()
                )
            ).hexdigest()[:16]
            filename = f"workspace-helper-{key}.jar"
            for directory in (self.vendor, self.cache):
                if (path := directory / filename).is_file():
                    return jars, path
            self.cache.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=self.cache, prefix="build-") as temporary:
                build = Path(temporary)
                await run_java_tool(
                    [
                        jdk["javac"],
                        "-J-Xmx256m",
                        "-J-Dfile.encoding=UTF-8",
                        "-J-Dstderr.encoding=UTF-8",
                        "--release",
                        "21",
                        "-proc:none",
                        "-encoding",
                        "UTF-8",
                        "-cp",
                        classpath(jars[1:]),
                        "-d",
                        build,
                        SOURCE,
                    ],
                    self.process_job,
                    60,
                    "A 端工作区 Java 辅助程序编译（需要 JDK 21+）",
                )
                with ZipFile(build / filename, "w", ZIP_DEFLATED) as jar:
                    for path in sorted(build.glob("WorkspaceTool*.class")):
                        jar.write(path, path.name)
                return jars, (build / filename).replace(self.cache / filename)

    def exec_environment(self, configured_path):
        env = os.environ.copy()
        names = (*JDK_TOOLS, "tools_dir", "asm_cp")
        for name in names:
            env.pop("MCAI_WORKSPACE_" + name.upper(), None)
        try:
            jdk = jdk_executables(configured_path)
        except ValueError:
            # A shell-only workspace can intentionally run without Java.
            jdk = {}
        env.update(
            {"MCAI_WORKSPACE_" + key.upper(): str(path) for key, path in jdk.items()}
        )
        asm = [
            self.local_dependency(key)
            for key in DEPENDENCIES
            if key.startswith("org/ow2/asm/")
        ]
        if all(asm):
            directory = (
                asm[0].parent if len({path.parent for path in asm}) == 1 else self.cache
            )
            env.update(
                MCAI_WORKSPACE_TOOLS_DIR=str(directory),
                MCAI_WORKSPACE_ASM_CP=classpath(asm),
            )
        return env
