"""Append-only Markdown cases, with an editable directory-to-document index."""

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path

from .paths import resolve_file
from .review import digest

CASE_MARKER = re.compile(r"^<!-- mcai-case (\S+) -->[ \t]*$", re.M)
INDEX_NOTE = "以上仅列出相关历史经验索引；需要完整排查步骤或原参数时，请按经验编号调用 mc_knowledge 读取详情。"


class Knowledge:
    def __init__(self, directory):
        self.directory = directory.resolve() / "knowledge"
        (self.directory / "servers").mkdir(parents=True, exist_ok=True)
        self.index = self.directory / "index.md"
        if not self.index.exists():
            self.index.write_text("# 服务端排障经验索引\n\n", encoding="utf-8")
        self.lock = asyncio.Lock()

    def entries(self, text=None, *, require_files=False):
        if text is None:
            text = self.index.read_text(encoding="utf-8")
        entries = []
        directories = set()
        for number, line in enumerate(text.split("\n"), 1):
            if "<!-- mcai-server" not in line:
                continue
            match = re.fullmatch(r"\s*<!-- mcai-server (.*?)-->\s*", line)
            try:
                if not match:
                    raise ValueError("索引注释须独占一行并以 --> 结束")
                try:
                    entry = json.loads(match[1])
                except json.JSONDecodeError as exc:
                    raise ValueError("索引注释不是有效 JSON，请修正后重试") from exc
                if not isinstance(entry, dict) or not all(
                    isinstance(entry.get(key), str) for key in ("directory", "file")
                ):
                    raise ValueError("须提供 directory 和 file 字符串")
                directory = entry["directory"]
                if (
                    not Path(directory).is_absolute()
                    or os.path.normcase(os.path.normpath(directory)) != directory
                ):
                    raise ValueError("directory 须为规范绝对目录")
                if directory in directories:
                    raise ValueError("directory 重复关联")
                path = self.document(entry["file"], allow_index=False)
                if require_files and not path.is_file():
                    raise ValueError(f"关联文档不存在：{entry['file']}")
                directories.add(directory)
                entries.append(entry)
            except (ValueError, OSError) as exc:
                raise ValueError(f"index.md 第 {number} 行：{exc}") from exc
        return entries

    def document(self, name, *, allow_index=True):
        if not isinstance(name, str):
            raise ValueError("经验文档名须为字符串")
        path = resolve_file(self.directory, name)
        if not (
            allow_index
            and name == "index.md"
            and path == self.index
            or re.fullmatch(r"servers/[^/\\:]+\.md", name)
            and path.parent == self.directory / "servers"
            and path.name == Path(name).name
        ):
            raise ValueError("请选择 index.md 或 servers 下的 Markdown 文档")
        return path

    def entry(self, directory):
        return next(
            (item for item in self.entries() if item["directory"] == directory), None
        )

    @staticmethod
    def cases(text):
        fields = CASE_MARKER.split(text)
        return dict(zip(fields[1::2], fields[2::2]))

    def query(self, args, directory=None):
        mode = args["mode"]
        if mode == "index":
            text = self.index.read_text(encoding="utf-8")
            self.entries(text)
        else:
            selected = args.get("directory", directory)
            entry = self.entry(selected)
            if not entry:
                return {"text": "该目录尚无已验收案例", "next_offset": None}
            text = resolve_file(self.directory, entry["file"]).read_text(
                encoding="utf-8"
            )
            if mode == "case":
                cases = self.cases(text)
                if args["case_id"] not in cases:
                    raise ValueError("该目录没有对应经验编号")
                text = cases[args["case_id"]].strip()
            elif mode == "search":
                lines = text.splitlines()
                hits = set()
                for index, line in enumerate(lines):
                    if args["query"].casefold() in line.casefold():
                        hits.update(
                            range(max(0, index - 2), min(len(lines), index + 5))
                        )
                text = "\n".join(f"{i + 1}: {lines[i]}" for i in sorted(hits))
        offset = args.get("offset", 0)
        end = min(offset + 12000, len(text))
        return {
            "text": text[offset:end],
            "next_offset": end if end < len(text) else None,
            "source": "历史经验，请核实当前版本与现场，不构成修复授权",
        }

    def context(self, directory, problem):
        entry = self.entry(directory)
        if entry is None:
            return {"cases": [], "message": "该目录尚无已验收案例"}
        text = resolve_file(self.directory, entry["file"]).read_text(encoding="utf-8")
        words = set(re.findall(r"[A-Za-z0-9_.:-]{3,}", problem.casefold()))
        for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", problem):
            words.update(phrase[index : index + 2] for index in range(len(phrase) - 1))
        ranked = []
        for case_id, body in reversed(self.cases(text).items()):
            folded = body.casefold()
            tags = sorted(
                (word for word in words if word in folded),
                key=lambda word: (-len(word), word),
            )
            if tags:
                ranked.append((len(tags), case_id, body, tags))
        ranked.sort(key=lambda item: -item[0])
        result = {"cases": [], "note": INDEX_NOTE}
        for _, case_id, body, tags in ranked[:4]:
            heading, _, detail = body.strip().partition("\n")
            summary = next(
                (
                    line.strip()
                    for line in detail.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                ),
                "",
            )
            result["cases"].append(
                {
                    "id": case_id,
                    "title": heading.removeprefix("## ")[:80],
                    "tags": [tag[:16] for tag in tags[:4]],
                    "summary": summary[:160],
                }
            )
            if len(json.dumps(result, ensure_ascii=False)) > 1600:
                result["cases"].pop()
        return result

    async def append(self, job, text):
        async with self.lock:
            directory = job["directory"]
            entry = self.entry(directory)
            if entry is None:
                entry = {
                    "directory": directory,
                    "file": "servers/" + digest(directory) + ".md",
                }
            path = resolve_file(self.directory, entry["file"])
            existing = (
                path.read_text(encoding="utf-8")
                if path.exists()
                else (f"# {job['instance']}\n\n服务端目录：`{directory}`\n\n")
            )
            marker = f"<!-- mcai-case {job['id']} -->"
            if marker not in existing:
                date = datetime.fromtimestamp(job["created"]).isoformat(
                    timespec="seconds"
                )
                content = (
                    existing
                    + f"\n{marker}\n## {job['name']} · {date}\n\n{text.strip()}\n"
                )
                temporary = path.with_suffix(".tmp")
                temporary.write_text(content, encoding="utf-8")
                os.replace(temporary, path)
            if self.entry(directory) is None:
                content = self.index.read_text(encoding="utf-8")
                content += (
                    "<!-- mcai-server "
                    + json.dumps(entry, ensure_ascii=False)
                    + " -->\n"
                    f"- [{job['instance']}]({entry['file']})：`{directory}`\n"
                )
                temporary = self.index.with_suffix(".tmp")
                temporary.write_text(content, encoding="utf-8")
                os.replace(temporary, self.index)
