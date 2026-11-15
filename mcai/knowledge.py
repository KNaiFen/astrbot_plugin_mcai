"""Append-only Markdown cases, with an editable directory-to-document index."""

import asyncio
import json
import os
import re
from datetime import datetime

from .paths import resolve_file
from .review import digest


class Knowledge:
    def __init__(self, directory):
        self.directory = directory / "knowledge"
        (self.directory / "servers").mkdir(parents=True, exist_ok=True)
        self.index = self.directory / "index.md"
        if not self.index.exists():
            self.index.write_text("# 服务端排障经验索引\n\n", encoding="utf-8")
        self.lock = asyncio.Lock()

    def entries(self):
        return [
            json.loads(value)
            for value in re.findall(
                r"<!-- mcai-server (.+?) -->", self.index.read_text(encoding="utf-8")
            )
        ]

    def entry(self, directory):
        return next(
            (item for item in self.entries() if item["directory"] == directory), None
        )

    def query(self, args, directory=None):
        mode = args["mode"]
        if mode == "index":
            text = self.index.read_text(encoding="utf-8")
        else:
            selected = args.get("directory", directory)
            entry = self.entry(selected)
            if not entry:
                return {"text": "该目录尚无已验收案例", "next_offset": None}
            text = resolve_file(self.directory, entry["file"]).read_text(
                encoding="utf-8"
            )
            if mode == "search":
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
            return {"cases": [], "matches": [], "message": "该目录尚无已验收案例"}
        text = resolve_file(self.directory, entry["file"]).read_text(encoding="utf-8")
        cases = re.split(r"(?=<!-- mcai-case )", text)[1:]
        words = set(re.findall(r"[A-Za-z0-9_.:-]{3,}", problem.casefold()))
        for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", problem):
            words.update(phrase[index : index + 2] for index in range(len(phrase) - 1))
        ranked = sorted(
            cases,
            key=lambda case: sum(word in case.casefold() for word in words),
            reverse=True,
        )
        return {
            "directory": directory,
            "cases": [line for line in text.splitlines() if line.startswith("## ")][
                -50:
            ],
            "matches": [
                case[:2000]
                for case in ranked[:3]
                if any(word in case.casefold() for word in words)
            ],
            "message": "仅为历史线索；使用 mc_history 分页核实完整内容及当前现场",
        }

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
