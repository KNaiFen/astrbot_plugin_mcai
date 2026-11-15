from pathlib import Path


def resolve_file(directory, relative):
    root = Path(directory).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("文件路径必须位于当前实例目录内")
    return path
