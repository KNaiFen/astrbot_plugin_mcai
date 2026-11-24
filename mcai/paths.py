import os
import re
from pathlib import Path


def _has_unsafe_windows_part(parts):
    return any(
        part not in ("", ".", "..")
        and (
            part.endswith((".", " "))
            or re.fullmatch(
                r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]",
                part.split(".")[0].rstrip(" "),
                re.I,
            )
            or re.search(r'[<>:"|?*\x00-\x1f]', part)
        )
        for part in parts
    )


def resolve_file(directory, relative):
    root = Path(directory).resolve()
    raw = Path(relative)
    if raw.is_absolute():
        path = raw.resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("文件路径必须位于当前实例目录内")
        raw_parts = raw.parts
        dir_parts = Path(directory).parts
        if len(raw_parts) > len(root.parts) and tuple(
            os.path.normcase(part) for part in raw_parts[: len(root.parts)]
        ) == tuple(os.path.normcase(part) for part in root.parts):
            check_parts = raw_parts[len(root.parts) :]
        elif len(raw_parts) > len(dir_parts) and tuple(
            os.path.normcase(part) for part in raw_parts[: len(dir_parts)]
        ) == tuple(os.path.normcase(part) for part in dir_parts):
            check_parts = raw_parts[len(dir_parts) :]
        else:
            check_parts = raw_parts[1:] if raw.anchor else raw_parts
        if _has_unsafe_windows_part(check_parts):
            raise ValueError("文件路径包含不安全的 Windows 文件名")
        return path
    if _has_unsafe_windows_part(str(relative).replace("\\", "/").split("/")):
        raise ValueError("文件路径包含不安全的 Windows 文件名")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("文件路径必须位于当前实例目录内")
    return path


def workspace_root(config, data_dir):
    return (Path(data_dir) / (config.get("workspace_dir") or "workspaces")).resolve()


def web_identity(value, *, attachment=False):
    if not isinstance(value, str) or not re.fullmatch(
        r"[a-f0-9]{32}-[0-2]" if attachment else r"[a-f0-9]{32}", value
    ):
        raise ValueError(
            "留证附件编号格式不正确" if attachment else "记录编号格式不正确"
        )
    return value
