import os
import shutil
import subprocess
from pathlib import Path

import psutil


def canonical_directory(path):
    return os.path.normcase(str(Path(path).resolve()))


def executable_status(path, detect):
    try:
        return {"path": path, "version": detect(path), "ready": True}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"path": path, "ready": False, "error": str(exc)}


def java_environment(config):
    env = os.environ.copy()
    configured = config.get("java_path")
    if configured:
        executable = Path(configured).expanduser().resolve()
        if not executable.is_file():
            raise ValueError(f"Java 路径不存在：{executable}")
        env["JAVA_HOME"] = str(executable.parent.parent)
        env["PATH"] = str(executable.parent) + os.pathsep + env.get("PATH", "")
        env["MCAI_JAVA"] = str(executable)
    return env


def java_executable(config):
    env = java_environment(config)
    executable = (
        env.get("MCAI_JAVA")
        if config.get("java_path")
        else shutil.which("java", path=env["PATH"])
    )
    if not executable:
        raise ValueError(
            "未找到 Java，请配置 world_tools.java_path 指向 Java 21+ 的 java.exe"
        )
    return str(Path(executable).resolve())


def leaf_java_processes(processes):
    """Oracle javapath launchers can themselves be java.exe parents of the JVM."""
    parents, java = {}, {}
    for process in processes:
        try:
            parent, name = process.ppid(), process.name().lower()
        except psutil.NoSuchProcess:
            continue  # A child can exit during the process-tree snapshot.
        parents[process.pid] = parent
        if name in ("java.exe", "javaw.exe"):
            java[process.pid] = process
    wrappers = set()
    for process in java.values():
        parent = parents[process.pid]
        while parent in parents:
            if parent in java:
                wrappers.add(parent)
            parent = parents[parent]
    return [process for pid, process in java.items() if pid not in wrappers]
