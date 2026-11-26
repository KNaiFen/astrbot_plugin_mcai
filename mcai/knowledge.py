"""Append-only Markdown cases, with an editable directory-to-document index."""

import asyncio
import json
import math
import os
import re
from collections import Counter
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from .environment import canonical_directory
from .paths import resolve_file
from .review import digest

CASE_MARKER = re.compile(r"^<!-- mcai-case (\S+) -->[ \t]*\r?$", re.M)
INDEX_NOTE = "以上仅列出相关历史经验索引；需要完整排查步骤或原参数时，请按经验编号调用 mc_knowledge 读取详情。"
SOURCE_NOTE = "历史经验，请核实当前版本与现场，不构成修复授权"
META_LINE = re.compile(
    r"^\s*- (标题|类型|状态|关键词|环境|替代案例)[：:]\s*(.*?)\s*$", re.M
)
# 中文按二元片段检索，排除运维叙述中的通用词，避免长日志凭泛词数量占据前列。
STOP_WORDS = frozenset(
    "服务 务器 问题 一下 可以 已经 没有 玩家 报错 日志 处理 尝试 开始 现在 还是 怎么 什么 我们 当前 任务 实例 情况 原因 解决 修复 排查 的是 这个 那个 进行 需要 一个 是否 以及 通过 确认 检查".split()
)


def terms(text):
    result = []
    for word in re.findall(r"[a-z0-9_.:/-]{2,}", text.casefold()):
        result.append(word)
        result.extend(
            part
            for part in re.split(r"[:/ _-]+", word)
            if len(part) >= 2 and part != word
        )
    for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        result.extend(
            phrase[i : i + 2]
            for i in range(len(phrase) - 1)
            if phrase[i : i + 2] not in STOP_WORDS
        )
    return result


def metadata(body):
    # 元信息只认首个小节之前的列表；正文中的引用和人工说明不声明状态。
    top = re.split(r"^#{1,6} ", body, maxsplit=1, flags=re.M)[0]
    return dict(META_LINE.findall(top))


def split_values(value):
    return list(
        dict.fromkeys(
            word
            for word in re.split(r"[,，、;；\s]+", value)
            if word and word not in ("无", "未知")
        )
    )


def parse_cases(text):
    text = text.replace("\r\n", "\n")
    markers = list(CASE_MARKER.finditer(text))
    result, previous = [], {}
    for i, marker in enumerate(markers):
        section = text[
            marker.end() : markers[i + 1].start() if i + 1 < len(markers) else len(text)
        ]
        lines = section.strip().split("\n", 1)
        heading = lines[0] if lines[0].startswith("## ") else ""
        title, date = heading.removeprefix("## ") or marker[1], None
        match = re.fullmatch(r"(.+) · (\d{4}-\d\d-\d\d(?:T[^\s]+)?)", title)
        if match:
            title, date = match.groups()
        body = ((lines[1] if len(lines) > 1 else "") if heading else section).strip()
        meta = metadata(body)
        conclusion = re.search(
            r"^### (?:结论与适用条件|结论)\s*\n(.*?)(?=^#{1,6} |\Z)", body, re.M | re.S
        )
        summary = ""
        if conclusion:
            for paragraph in re.split(r"\n\s*\n", conclusion[1]):
                usable = [
                    line.strip()
                    for line in paragraph.splitlines()
                    if line.strip()
                    and not line.lstrip().startswith("#")
                    and not META_LINE.fullmatch(line)
                ]
                if usable:
                    summary = " ".join(usable)
                    break
        if not summary:
            summary = next(
                (
                    line.strip()
                    for line in body.splitlines()
                    if line.strip()
                    and not line.lstrip().startswith("#")
                    and not META_LINE.fullmatch(line)
                ),
                "",
            )
        supersedes = [
            key
            for key in split_values(meta.get("替代案例", ""))
            if key in previous and key != marker[1]
        ]
        row = {
            "id": marker[1],
            "heading": heading,
            "title": title,
            "date": date,
            "body": body,
            "category": meta.get("类型", ""),
            "keywords": split_values(meta.get("关键词", "")),
            "environment": meta.get("环境", ""),
            "declared_status": "superseded"
            if meta.get("状态") == "superseded"
            else "active",
            "supersedes": supersedes,
            "superseded_by": [],
            "summary": summary,
            "_section": section,
            "_line": text.count("\n", 0, marker.end()) + 1,
        }
        for key in supersedes:
            previous[key]["superseded_by"].append(marker[1])
        previous[marker[1]] = row
        result.append(row)
    for row in result:
        row["status"] = (
            "superseded"
            if row["superseded_by"] or row["declared_status"] == "superseded"
            else "active"
        )
        vector = Counter(terms(row["body"]))
        vector.update(
            {
                key: count * 3
                for key, count in Counter(
                    terms(row["title"] + " " + " ".join(row["keywords"]))
                ).items()
            }
        )
        vector.update(
            {key: count * 2 for key, count in Counter(terms(row["summary"])).items()}
        )
        row["_terms"], row["_length"] = vector, sum(vector.values())
    return result


class Knowledge:
    def __init__(self, directory):
        self.directory = directory.resolve() / "knowledge"
        (self.directory / "servers").mkdir(parents=True, exist_ok=True)
        self.index = self.directory / "index.md"
        if not self.index.exists():
            self.index.write_text("# 服务端排障经验索引\n\n", encoding="utf-8")
        self.lock = asyncio.Lock()
        self._cache = {}

    def parsed_document(self, path, text=None):
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        cached = self._cache.get(path)
        if cached is None or cached[0] != signature:
            if text is None:
                text = path.read_text(encoding="utf-8")
            cached = (signature, parse_cases(text), self.title(text, path.stem))
            self._cache[path] = cached
        return cached[1], cached[2]

    def parsed(self, path, text=None):
        return self.parsed_document(path, text)[0]

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
            cases = [
                {key: value for key, value in row.items() if not key.startswith("_")}
                for row in self.parsed(self.web_document(name, allow_index=False), text)
            ]
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
        if mode in ("list", "search"):
            return self.catalog(args, directory)
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
        offset = args.get("offset", 0)
        end = min(offset + 12000, len(text))
        return {
            "text": text[offset:end],
            "next_offset": end if end < len(text) else None,
            "source": SOURCE_NOTE,
        }

    @staticmethod
    def rank(rows, query, *, prefer_active=False):
        words = set(terms(query))
        if not words or not rows:
            return []
        frequency = Counter(
            word for row in rows for word in words if word in row["_terms"]
        )
        average = sum(row["_length"] for row in rows) / len(rows) or 1
        phrases = [
            part.casefold()
            for part in re.findall(r"[\u4e00-\u9fff]{3,}|[A-Za-z0-9_.:/-]{2,}", query)
            if terms(part)
        ]
        ranked = []
        for i, row in enumerate(rows):
            tags = sorted(
                words & row["_terms"].keys(), key=lambda word: (-len(word), word)
            )
            if not tags:
                continue
            score = 0
            for word in tags:
                count = row["_terms"][word]
                idf = math.log(
                    1 + (len(rows) - frequency[word] + 0.5) / (frequency[word] + 0.5)
                )
                score += (
                    idf
                    * count
                    * 2.2
                    / (count + 1.2 * (0.25 + 0.75 * row["_length"] / average))
                )
            folded = (row["title"] + "\n" + row["body"]).casefold()
            score += sum(0.5 for phrase in phrases if phrase in folded)
            if query.strip().casefold() in folded:
                score += 0.5
            score *= 1 + 0.03 * i / len(rows)
            ranked.append((score, i, row, tags))
        if prefer_active and any(row["status"] == "active" for _, _, row, _ in ranked):
            ranked = [
                (score * (0.25 if row["status"] == "superseded" else 1), i, row, tags)
                for score, i, row, tags in ranked
            ]
        return sorted(
            ranked,
            key=lambda item: (item[0], item[2]["date"] or "", item[1]),
            reverse=True,
        )

    def catalog(self, args, directory):
        mode = args["mode"]
        all_servers = args.get("all_servers", False)
        if all_servers and "directory" in args:
            raise ValueError("all_servers=true 不能同时指定 directory")
        query = args.get("query", "").strip()
        if mode == "search" and not query:
            raise ValueError("query 不能为空白")
        entries = (
            self.entries()
            if all_servers
            else [self.entry(args.get("directory", directory))]
        )
        rows, warnings = [], []
        for entry in entries:
            if entry is None:
                continue
            path = self.document(entry["file"], allow_index=False)
            if all_servers and not path.is_file():
                warnings.append(f"关联文档不存在：{entry['file']}")
                continue
            parsed_rows, instance_title = self.parsed_document(path)
            for row in parsed_rows:
                rows.append(
                    {
                        **row,
                        "directory": entry["directory"],
                        "instance_title": instance_title if mode == "search" else "",
                    }
                )
        status = args.get("status", "active")
        filtered = [
            row
            for row in rows
            if (status == "all" or row["status"] == status)
            and (not args.get("category") or row["category"] == args["category"])
        ]
        offset, limit = (
            args.get("offset", 0),
            args.get("limit", 20 if mode == "list" else 8),
        )
        source = SOURCE_NOTE + ("；跨服经验须核对版本与环境差异" if all_servers else "")
        if mode == "list":
            selected = list(reversed(filtered))
            result = {
                "total": len(selected),
                "total_all": len(rows),
                "superseded_count": sum(row["status"] == "superseded" for row in rows),
                "offset": offset,
                "next_offset": None,
                "items": [],
                "source": source,
            }
        else:
            selected = self.rank(filtered, query, prefer_active=True)
            # 保留既有 text 契约；每个案例仅输出一次片段，避免与 matches 重复占用上下文。
            result = {
                "total_matches": len(selected),
                "offset": offset,
                "next_offset": None,
                "text": "",
                "source": source,
            }
        if warnings:
            result["warnings"] = warnings[:8]
            result["warning_count"] = len(warnings)
            if len(warnings) > 8:
                result["warnings"].append(
                    f"另有{len(warnings) - 8}个关联文档缺失，请核对index.md"
                )
        count = 0
        for item in selected[offset : offset + limit]:
            if mode == "list":
                row = item
                value = {
                    key: row[key]
                    for key in (
                        "id",
                        "title",
                        "date",
                        "status",
                        "category",
                        "supersedes",
                        "superseded_by",
                    )
                }
                value.update(keywords=row["keywords"][:6], summary=row["summary"][:160])
                result["items"].append(value)
            else:
                _, _, row, tags = item
                lines = row["_section"].splitlines()
                hits = [
                    i
                    for i, line in enumerate(lines)
                    if not line.lstrip().startswith("#")
                    and not META_LINE.fullmatch(line)
                    and any(word in line.casefold() for word in tags)
                ]
                if not hits:
                    hits = [
                        i
                        for i, line in enumerate(lines)
                        if any(word in line.casefold() for word in tags)
                    ]
                snippets, covered = [], -1
                for hit in hits:
                    if hit <= covered:
                        continue
                    start, end = max(0, hit - 1), min(len(lines), hit + 2)
                    snippets.append(
                        "\n".join(
                            f"{row['_line'] + i}: {lines[i]}" for i in range(start, end)
                        )[:400]
                    )
                    covered = end - 1
                    if len(snippets) == 2:
                        break
                header = {
                    "case_id": row["id"],
                    **{
                        key: row[key]
                        for key in (
                            "title",
                            "date",
                            "status",
                            "superseded_by",
                            "directory",
                            "instance_title",
                        )
                    },
                    "matched_terms": tags[:6],
                }
                value = (
                    f"[{row['id']}] "
                    + json.dumps(header, ensure_ascii=False)
                    + "\n"
                    + "\n".join(snippets)
                    + "\n\n"
                )
                result["text"] += value
            count += 1
            result["next_offset"] = (
                offset + count if offset + count < len(selected) else None
            )
            if len(json.dumps(result, ensure_ascii=False)) > 11900:
                if mode == "list":
                    result["items"].pop()
                else:
                    result["text"] = result["text"][: -len(value)]
                count -= 1
                if count == 0:
                    raise ValueError("案例目录字段过长，请精简该案例标题或元信息后重试")
                break
        result["next_offset"] = (
            offset + count if offset + count < len(selected) else None
        )
        if not rows:
            result["source"] += "；该目录尚无已验收案例"
        return result

    def context(self, directory, problem, *, exclude=None):
        entry = self.entry(directory)
        rows = (
            [
                row
                for row in self.parsed(self.document(entry["file"], allow_index=False))
                if row["id"] != exclude
            ]
            if entry
            else []
        )
        result = {
            "total_cases": len(rows),
            "active_cases": sum(row["status"] == "active" for row in rows),
            "cases": [],
            "note": INDEX_NOTE,
        }
        ranked = self.rank(rows, problem, prefer_active=True)
        result["matched"] = bool(ranked)
        for _, _, row, tags in ranked[:4]:
            item = {key: row[key] for key in ("id", "date", "status")}
            item.update(
                title=row["title"][:80],
                tags=[tag[:16] for tag in tags[:4]],
                keywords=row["keywords"][:6],
                summary=row["summary"][:160],
            )
            if row["superseded_by"]:
                item["superseded_by"] = row["superseded_by"]
            result["cases"].append(item)
        field = "cases"
        if not ranked and rows:
            field = "recent_cases"
            result[field] = [
                {
                    "id": row["id"],
                    "title": row["title"][:80],
                    "date": row["date"],
                    "summary": row["summary"][:80],
                }
                for row in reversed(rows)
                if row["status"] == "active"
            ][:3]
            result["note"] = (
                "未按关键词直接命中；以上为本服最近案例，可用 mc_history(mode='list') 或 mc_history(mode='search') 检索全部历史"
            )
        elif not rows:
            result["message"] = "该目录尚无已验收案例"
        while result[field] and len(json.dumps(result, ensure_ascii=False)) > 1600:
            result[field].pop()
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
                semantic_title = metadata(text).get("标题", "")
                title = job["name"]
                if semantic_title and semantic_title != title:
                    title += " — " + semantic_title
                content = (
                    existing + f"\n{marker}\n## {title} · {date}\n\n{text.strip()}\n"
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
