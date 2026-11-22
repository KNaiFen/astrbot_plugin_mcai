import re
from pathlib import Path


def resolve_file(directory, relative):
    root = Path(directory).resolve()
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
