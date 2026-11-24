"""Append-only Markdown cases, with an editable directory-to-document index."""

import asyncio
import json
import os
import re
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from .environment import canonical_directory
from .paths import resolve_file
from .review import digest

CASE_MARKER = re.compile(r"^<!-- mcai-case (\S+) -->[ \t]*\r?$", re.M)
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

    def web_document(self, name, *, allow_index=True):
        path = self.document(name, allow_index=allow_index)
        if any(
            item.is_symlink() or item.is_junction()
            for item in (self.directory, path.parent, self.directory / name)
        ):
            raise ValueError("经验文档路径不能是链接")
        return path

    @staticmethod
    def title(text, fallback):
        heading = re.search(r"^# (.+)$", text, re.M)
        return heading[1].strip() if heading else fallback

    def web_read(self, name=None):
        if name == "index.md":
            data = self.web_document(name).read_bytes()
            return {
                "name": name,
                "text": data.decode("utf-8"),
                "revision": sha256(data).hexdigest(),
            }
        index = self.web_document("index.md").read_bytes()
        index_info = {"index_revision": sha256(index).hexdigest()}
        try:
            entries = self.entries(index.decode("utf-8"))
        except ValueError as exc:
            entries = []
            index_info["index_error"] = str(exc)
        directories = {}
        for entry in entries:
            directories.setdefault(entry["file"], entry["directory"])
        if name is not None:
            data = self.web_document(name, allow_index=False).read_bytes()
            text = data.decode("utf-8")
            cases = []
            for case_id, section in self.cases(text.replace("\r\n", "\n")).items():
                lines = section.strip().split("\n", 1)
                heading = lines[0] if lines[0].startswith("## ") else ""
                title = heading.removeprefix("## ") or case_id
                date = None
                match = re.fullmatch(r"(.+) · (\d{4}-\d\d-\d\d(?:T[^\s]+)?)", title)
                if match:
                    title, date = match.groups()
                body = (lines[1] if len(lines) > 1 else "") if heading else section
                cases.append(
                    {
                        "id": case_id,
                        "heading": heading,
                        "title": title,
                        "date": date,
                        "body": body.strip(),
                    }
                )
            return {
                "name": name,
                "text": text,
                "revision": sha256(data).hexdigest(),
                "cases": cases,
                "header": CASE_MARKER.split(text, maxsplit=1)[0],
                "directory": directories.get(name),
            }
        items = []
        for path in sorted((self.directory / "servers").glob("*.md")):
            if not path.is_file() or path.is_symlink():
                continue
            file = f"servers/{path.name}"
            data = self.web_document(file, allow_index=False).read_bytes()
            text = data.decode("utf-8")
            items.append(
                {
                    "file": file,
                    "title": self.title(text, path.stem),
                    "directory": directories.get(file),
                    "linked": file in directories,
                    "case_count": len(self.cases(text)),
                    "revision": sha256(data).hexdigest(),
                }
            )
        return {
            **index_info,
            "entries": entries,
            "items": items,
            "documents": ["index.md", *(row["file"] for row in items)],
        }

    @staticmethod
    def write_document(path, text):
        temporary = path.with_suffix(".tmp")
        if temporary.is_symlink() or temporary.is_junction():
            raise ValueError("文档临时路径不能是链接")
        updated = text.encode("utf-8")
        temporary.write_bytes(updated)
        os.replace(temporary, path)
        return sha256(updated).hexdigest()

    @staticmethod
    def check_revision(data, revision):
        if sha256(data).hexdigest() != revision:
            raise ValueError("文档已变化，请重新打开后再保存")

    def web_save(self, body):
        action = body.get("action")
        if action in ("set_association", "create_server_doc", "remove_association"):
            return self.change_association(action, body)
        if action not in (None, "upsert_case", "delete_case", "delete_orphan"):
            raise ValueError("未知的经验文档操作")
        name = body["file"] if action == "delete_orphan" else body["name"]
        path = self.web_document(name, allow_index=action is None)
        data = path.read_bytes()
        self.check_revision(data, body.get("revision"))
        if action == "delete_orphan":
            index = self.web_document("index.md").read_text(encoding="utf-8")
            if any(
                row["file"] == name for row in self.entries(index, require_files=True)
            ):
                raise ValueError("文档仍有关联目录，请先解除关联")
            path.unlink()
            return name, {"deleted": True}
        if action is None:
            text = body["text"]
            if not isinstance(text, str):
                raise ValueError("正文必须是 Markdown 文本")
            if name == "index.md":
                self.entries(text, require_files=True)
        else:
            text = data.decode("utf-8")
            case_id = body.get("case_id")
            markers = list(CASE_MARKER.finditer(text))
            if action == "delete_case" or case_id is not None:
                matches = [
                    i for i, marker in enumerate(markers) if marker[1] == case_id
                ]
                if len(matches) != 1:
                    raise ValueError("经验编号不存在或重复")
                i = matches[0]
                start = markers[i].start()
                end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
            else:
                case_id = "manual-" + uuid4().hex[:12]
                start = end = len(text)
            replacement = ""
            if action == "upsert_case":
                title, content, date = body["title"], body["body"], body.get("date")
                if (
                    not isinstance(title, str)
                    or not title.strip()
                    or len(title.splitlines()) != 1
                    or not isinstance(content, str)
                    or "<!-- mcai-case" in content
                    or "<!-- mcai-case" in title
                ):
                    raise ValueError("请填写单行标题和正文，正文不能包含经验标记")
                if date not in (None, ""):
                    if not isinstance(date, str) or len(date.splitlines()) != 1:
                        raise ValueError("日期须为 ISO 日期或时间")
                    parsed = datetime.fromisoformat(date)
                    date = (
                        parsed.date().isoformat()
                        if len(date) <= 10
                        else parsed.isoformat()
                    )
                newline = "\r\n" if "\r\n" in text else "\n"
                heading = title.strip() + (f" · {date}" if date else "")
                section = f"<!-- mcai-case {case_id} -->\n## {heading}\n\n{content.strip()}\n\n"
                replacement = section.replace("\r\n", "\n").replace("\n", newline)
                if start == len(text) and text:
                    replacement = (
                        newline if text.endswith(("\n", "\r")) else newline * 2
                    ) + replacement
            text = text[:start] + replacement + text[end:]
        return name, {"saved": True, "revision": self.write_document(path, text)}

    def change_association(self, action, body):
        index = self.web_document("index.md")
        data = index.read_bytes()
        if action == "set_association" or body.get("index_revision") is not None:
            self.check_revision(data, body.get("index_revision"))
        directory = body.get("directory")
        if not isinstance(directory, str) or not Path(directory.strip()).is_absolute():
            raise ValueError("服务端目录须为绝对路径")
        directory = canonical_directory(directory.strip())
        lines = data.decode("utf-8").splitlines(keepends=True)
        entries = self.entries(data.decode("utf-8"), require_files=True)
        match = next((row for row in entries if row["directory"] == directory), None)
        if action == "remove_association":
            if match is None:
                raise ValueError("目录没有关联文档")
            old, name = match, match["file"]
        else:
            name = (
                "servers/" + digest(directory) + ".md"
                if action == "create_server_doc"
                else body.get("file")
            )
            path = self.web_document(name, allow_index=False)
            linked = [row for row in entries if row["file"] == name]
            if action == "set_association" and len(linked) > 1:
                raise ValueError("文档关联了多个目录，请先解除多余的关联")
            old = linked[0] if linked and action == "set_association" else None
            if match and match != old:
                raise ValueError("该目录已经关联")
            title = body.get("instance_name")
            if action == "create_server_doc" and title is None:
                raise ValueError("请填写实例名")
            if title is not None and (
                not isinstance(title, str)
                or not title.strip()
                or len(title.splitlines()) != 1
                or "<!-- mcai-server" in title
            ):
                raise ValueError("实例名须为单行文本")
            if path.is_file():
                title = title or self.title(path.read_text(encoding="utf-8"), path.stem)
            elif action == "create_server_doc" and title:
                self.write_document(path, f"# {title}\n\n服务端目录：`{directory}`\n\n")
            else:
                raise ValueError("请选择现有文档或填写实例名")
        if old:
            for i, line in enumerate(lines):
                if "<!-- mcai-server" in line and self.entries(line) == [old]:
                    end = i + 1
                    if (
                        end < len(lines)
                        and f"]({old['file']})" in lines[end]
                        and lines[end].lstrip().startswith("- [")
                    ):
                        end += 1
                    del lines[i:end]
                    break
        text = "".join(lines)
        if action != "remove_association":
            entry = json.dumps(
                {"directory": directory, "file": name}, ensure_ascii=False
            )
            safe_title = title.replace("[", r"\[").replace("]", r"\]")
            text = (
                text.rstrip("\r\n")
                + f"\n\n<!-- mcai-server {entry} -->\n- [{safe_title}]({name})：`{directory}`\n"
            )
        self.entries(text, require_files=True)
        return "index.md", {
            "saved": True,
            "file": name,
            "index_revision": self.write_document(index, text),
        }

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
            raw_directory = job["directory"]
            if (
                not isinstance(raw_directory, str)
                or not Path(raw_directory).is_absolute()
            ):
                raise ValueError("directory 须为规范绝对目录")
            directory = canonical_directory(raw_directory)
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
                text = text.replace("<!-- mcai-case", "&lt;!-- mcai-case").replace(
                    "<!-- mcai-server", "&lt;!-- mcai-server"
                )
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
                if content:
                    content = content.rstrip("\r\n") + "\n\n"
                content += (
                    "<!-- mcai-server "
                    + json.dumps(entry, ensure_ascii=False)
                    + " -->\n"
                    f"- [{job['instance']}]({entry['file']})：`{directory}`\n"
                )
                self.entries(content)
                temporary = self.index.with_suffix(".tmp")
                temporary.write_text(content, encoding="utf-8")
                os.replace(temporary, self.index)
