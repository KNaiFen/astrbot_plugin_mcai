"""Host settings, validated PowerShell 7 and atomic instance configuration."""

import codecs
import ctypes
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from threading import Lock

from .environment import canonical_directory

RESTART_PROMPT = "Start server in 10 seconds. Press ctrl+c to stop right now."
WRITE_LOCK = Lock()
DEFAULT_INCIDENT_RESTART_WINDOW = 120
DEFAULT_INCIDENT_CAPACITY = 256
ALERT_DEFAULTS = {
    "alert_window": True,
    "alert_window_minutes": 3,
    "alert_disk": True,
    "alert_disk_gib": 10,
    "alert_performance": False,
    "alert_mspt": 50,
    "alert_performance_minutes": 3,
}


def launcher_identity(config):
    return hashlib.sha256(
        json.dumps(
            {
                key: config.get(key)
                for key in (
                    "directory",
                    "java_path",
                    "powershell_path",
                    "encoding",
                    "stop_command",
                    "stop_timeout",
                    "restart_prompt",
                )
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        temporary.write_bytes(data)
        with WRITE_LOCK:
            temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return data


def powershell_path(configured=""):
    candidate = configured or shutil.which("pwsh.exe" if os.name == "nt" else "pwsh")
    if not candidate and os.name == "nt":
        candidate = str(Path(os.environ["ProgramFiles"]) / "PowerShell/7/pwsh.exe")
    if not candidate or not Path(candidate).is_file():
        raise ValueError(
            "未找到 PowerShell 7，请在 powershell_path 填写 pwsh.exe 的完整路径"
        )
    powershell_version(candidate)
    return str(Path(candidate).resolve())


def powershell_version(candidate):
    result = subprocess.run(
        [
            str(candidate),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$PSVersionTable.PSVersion.ToString()",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=True,
    )
    version = result.stdout.strip()
    if not re.fullmatch(r"7\.(?:[3-9]|[1-9][0-9]+)\.\d+(?:[-+].*)?", version):
        raise ValueError(f"需要 PowerShell 7.3+ 的 7.x 版本，当前为 {version}")
    return version


def bat_codepage(path, encoding="auto", data=None):
    if data is None:
        data = Path(path).read_bytes()
    if data.startswith(
        (
            codecs.BOM_UTF16_LE,
            codecs.BOM_UTF16_BE,
            codecs.BOM_UTF32_LE,
            codecs.BOM_UTF32_BE,
        )
    ):
        raise ValueError(
            "CMD 不支持 UTF-16/UTF-32 BAT，请将启动 BAT 保存为 UTF-8 或系统 ANSI 编码"
        )
    if encoding != "auto":
        try:
            normalized = codecs.lookup(encoding).name
        except LookupError as exc:
            raise ValueError(f"未知 BAT 编码：{encoding}") from exc
        if normalized in ("utf-8", "utf-8-sig"):
            return 65001
        if normalized in ("gbk", "gb18030"):
            return 936
        if normalized.startswith("cp") and normalized[2:].isdigit():
            return int(normalized[2:])
        raise ValueError("BAT 编码请填写 auto、utf-8、gbk 或 Windows cp 编号")
    try:
        data.decode("utf-8-sig")
        return (
            65001
            if any(byte >= 128 for byte in data)
            else (ctypes.windll.kernel32.GetACP() if os.name == "nt" else 65001)
        )
    except UnicodeDecodeError:
        page = ctypes.windll.kernel32.GetACP() if os.name == "nt" else 936
        data.decode(f"cp{page}")
        return page


def allowed_group_ids(values):
    """返回配置中去除空白并忽略空项后的允许群号集合。"""
    return {
        text
        for item in (values or ())
        if item is not None and (text := str(item).strip())
    }


def incident_routes(values, allowed):
    routes = {}
    groups = allowed_group_ids(allowed)
    for value in values:
        match = re.fullmatch(
            r"([A-Za-z0-9_-]+)=([^:\s=]+:GroupMessage:(\d+))", str(value)
        )
        if not match or match[1] in routes:
            raise ValueError(
                "故障通知须按 实例=平台ID:GroupMessage:群号 配置，实例不能重复"
            )
        if groups and match[3] not in groups:
            raise ValueError("故障通知目标必须在允许群号中")
        routes[match[1]] = match[2]
    return routes


LEGACY_TEST_FIELDS = {"test_address", "test_port"}


def host_test_settings(config):
    address, port = config.get("test_address", ""), config.get("test_port")
    if isinstance(address, str):
        address = address.strip()
        if (not address and port is None) or (
            address and type(port) is int and 1 <= port <= 65535
        ):
            return {"test_address": address, "test_port": port}
    raise ValueError(
        "全局测试服须同时填写可达地址（test_address）和有效端口（test_port，1–65535）"
    )


def normalize_instances(values, base, shell):
    if not isinstance(values, dict):
        raise ValueError("instances.json 必须是服务端名称到配置的对象")
    result, directories = {}, set()
    for name, value in values.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or not isinstance(value, dict):
            raise ValueError("实例名只允许字母、数字、下划线和短横线")
        allowed = {
            "directory",
            "description",
            "java_path",
            "encoding",
            "stop_timeout",
            "stop_command",
            "restart_prompt",
            *LEGACY_TEST_FIELDS,
            "test_copy_paths",
            "incident_watch",
            *ALERT_DEFAULTS,
        }
        if set(value) - allowed:
            raise ValueError(
                f"{name}：未知实例字段：{', '.join(sorted(set(value) - allowed))}"
            )
        if (
            not isinstance(value.get("directory"), str)
            or not value["directory"].strip()
        ):
            raise ValueError(f"{name}：directory 需要服务端目录字符串")
        if (
            not isinstance(value.get("description", ""), str)
            or not isinstance(value.get("java_path", ""), str)
            or not isinstance(value.get("encoding", "auto"), str)
            or not isinstance(value.get("restart_prompt", RESTART_PROMPT), str)
            or not isinstance(value.get("stop_command", "stop"), str)
        ):
            raise ValueError(f"{name}：说明、路径、编码和停服提示必须是字符串")
        if type(value.get("stop_timeout", 120)) not in (int, float):
            raise ValueError("stop_timeout 必须是秒数")
        if type(value.get("incident_watch", False)) is not bool:
            raise ValueError("incident_watch 必须是布尔值")
        for key, default in ALERT_DEFAULTS.items():
            setting = value.get(key, default)
            if isinstance(default, bool):
                if type(setting) is not bool:
                    raise ValueError(f"{name}：{key} 必须是布尔值")
            elif type(setting) not in (int, float) or not 0 < setting < math.inf:
                raise ValueError(f"{name}：{key} 必须是有限正数")
        if "test_copy_paths" in value and (
            not isinstance(value["test_copy_paths"], list)
            or any(
                not isinstance(item, str) or not item.strip()
                for item in value["test_copy_paths"]
            )
        ):
            raise ValueError(f"{name}：test_copy_paths 必须是路径字符串列表")
        path = (Path(base) / value["directory"]).resolve()
        if not path.is_dir():
            raise ValueError(f"{name}：服务端目录不存在：{path}")
        directory = canonical_directory(path)
        if directory in directories:
            raise ValueError("多个实例指向同一规范化目录，请只保留一个配置")
        directories.add(directory)
        configured = {
            **{
                key: item
                for key, item in value.items()
                if key not in LEGACY_TEST_FIELDS
            },
            "directory": str(path),
            "powershell_path": shell,
        }
        if value.get("java_path"):
            configured["java_path"] = str((Path(base) / value["java_path"]).resolve())
            if not Path(configured["java_path"]).is_file():
                raise ValueError(f"{name}：Java 路径不存在")
        if not 0 < value.get("stop_timeout", 120) <= 3600:
            raise ValueError("stop_timeout 必须大于 0 且不超过 3600 秒")
        if (path / "start.bat").exists():
            bat_codepage(path / "start.bat", value.get("encoding", "auto"))
        if not value.get("restart_prompt", RESTART_PROMPT).strip():
            raise ValueError("restart_prompt 不能为空")
        result[name] = configured
    return result


def incident_restart_window(value):
    if type(value) is not int or value < 1:
        raise ValueError("启动失败统计窗口须为正整数秒")
    return value


def incident_capacity(value):
    if type(value) is not int or not 64 <= value <= 4096:
        raise ValueError("主动留证容量须为 64 至 4096 MiB 的整数")
    return value


def host_storage_settings(config, parent, data_dir):
    directories = {}
    for key, default in (
        ("scheduled_backup_dir", "backups"),
        ("workspace_dir", "workspaces"),
    ):
        value = config.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"{key} 必须是目录路径")
        path = (parent / value if value.strip() else Path(data_dir) / default).resolve()
        if path.exists() and not path.is_dir():
            raise ValueError(f"{key} 不能指向文件：{path}")
        directories[key] = str(path)
    size = config.get("download_max_bytes", 2 * 1024**3)
    if type(size) is not int or size < 1:
        raise ValueError("单文件下载上限须为正整数（字节）")
    return {**directories, "download_max_bytes": size}


def load_host(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if "instances" in config:
        raise ValueError("请将实例配置放入 instances_file 指定的独立文件")
    if config.get("tls", True) is not True:
        raise ValueError("MC 控制程序仅支持 HTTPS，tls 必须为 true")
    memory = config.get("operations_memory_limit_mib", 8192)
    if type(memory) is not int or memory < 64:
        raise ValueError("operations_memory_limit_mib 必须是至少 64 的整数")
    config["operations_memory_limit_mib"] = memory
    config["incident_restart_window_seconds"] = incident_restart_window(
        config.get("incident_restart_window_seconds", DEFAULT_INCIDENT_RESTART_WINDOW)
    )
    config["incident_capacity_mib"] = incident_capacity(
        config.get("incident_capacity_mib", DEFAULT_INCIDENT_CAPACITY)
    )
    shell = powershell_path(
        str((path.parent / config["powershell_path"]).resolve())
        if config.get("powershell_path")
        else ""
    )
    instance_path = (
        path.parent / config.get("instances_file", "instances.json")
    ).resolve()
    values = json.loads(instance_path.read_text(encoding="utf-8-sig"))
    config.update(
        instances=normalize_instances(values, instance_path.parent, shell),
        powershell_path=shell,
        _config_path=str(path),
        _instances_path=str(instance_path),
    )
    config["data_dir"] = str(
        (path.parent / config.get("data_dir", "runtime/host")).resolve()
    )
    config.update(host_storage_settings(config, path.parent, config["data_dir"]))
    config.update(host_test_settings(config))
    if config.get("world_tools", {}).get("java_path"):
        config["world_tools"]["java_path"] = str(
            (path.parent / config["world_tools"]["java_path"]).resolve()
        )
    return config
