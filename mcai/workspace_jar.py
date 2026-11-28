"""Bounded ZIP and JVM class reads for A-side task workspaces."""

import io
import json
import re
import struct
from contextlib import contextmanager
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

MIB = 1024**2
JAR_BYTES = 1024 * MIB
JAR_ENTRIES = 100_000
NESTED_BYTES = 64 * MIB
SIGNATURE = re.compile(r"META-INF/(?:[^/]+\.(?:SF|DSA|RSA|EC)|SIG-[^/]+)", re.I)
BINARY_EXTENSIONS = {
    ".class",
    ".jar",
    ".zip",
    ".gz",
    ".7z",
    ".rar",
    ".xz",
    ".zst",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".ico",
    ".ogg",
    ".wav",
    ".mp3",
    ".mp4",
    ".flac",
    ".nbt",
    ".mca",
    ".so",
    ".dll",
    ".exe",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".pdf",
}


def entry_name(value):
    if not isinstance(value, str) or any(
        part in ("", ".", "..") or re.search(r"[\\:\x00-\x1f]", part)
        for part in value.split("/")
    ):
        raise ValueError(f"JAR 条目必须是使用正斜杠的相对路径：{value!r}")
    return value


def checked_entries(jar, *, bytes_left=JAR_BYTES, entries_left=JAR_ENTRIES):
    entries = jar.infolist()
    if len(entries) > entries_left or sum(i.file_size for i in entries) > bytes_left:
        raise ValueError("JAR 条目总数或解压后大小超过上限（100000 条、1 GiB）")
    if len(jar.NameToInfo) != len(entries):
        seen = set()
        for item in entries:
            if item.filename in seen:
                raise ValueError(f"JAR 包含重复条目：{item.filename[:200]}")
            seen.add(item.filename)
    return entries


def find_entry(jar, name):
    if (item := jar.NameToInfo.get(entry_name(name))) is None or item.is_dir():
        raise ValueError(f"JAR 中没有指定条目：{name}")
    return item


def nested_entry(jar, name):
    item = find_entry(jar, name)
    if not name.lower().endswith(".jar"):
        raise ValueError(f"嵌套条目不是 .jar：{name}")
    if item.file_size > NESTED_BYTES:
        raise ValueError(f"嵌套 JAR 超过 64 MiB：{name}")
    return item


@contextmanager
def open_nested(jar, name):
    try:
        with ZipFile(io.BytesIO(jar.read(nested_entry(jar, name)))) as nested:
            yield nested
    except BadZipFile as error:
        raise ValueError(f"嵌套 JAR 不是有效 ZIP 或内容已损坏：{name}") from error


@contextmanager
def open_jar(path, nested=None):
    with ZipFile(path) as jar:
        entries = checked_entries(jar)
        if nested is None:
            yield jar, entries
        else:
            with open_nested(jar, nested) as inner:
                yield (
                    inner,
                    checked_entries(
                        inner,
                        bytes_left=JAR_BYTES - sum(i.file_size for i in entries),
                        entries_left=JAR_ENTRIES - len(entries),
                    ),
                )


def is_text(text):
    return not re.search(r"[\x00-\x08\x0b\x0e-\x1f]", text)


def binary_entry(name):
    return PurePosixPath(name).suffix.lower() in BINARY_EXTENSIONS


def class_names(args):
    names = args["class_names"]
    if (
        not isinstance(names, list)
        or not 1 <= len(names) <= 10
        or any(
            not isinstance(name, str)
            or len(name) > 240
            or not all(
                part.replace("$", "_").isidentifier() for part in name.split(".")
            )
            for name in names
        )
    ):
        raise ValueError("class_names 须包含 1 至 10 个 Java 二进制类名")
    return names


def class_symbols(raw):
    offset = 0

    def take(size):
        nonlocal offset
        end = offset + size
        if end > len(raw):
            raise ValueError("class 内容不完整")
        block = raw[offset:end]
        offset = end
        return block

    def number(size=2):
        return int.from_bytes(take(size), "big")

    if take(4) != b"\xca\xfe\xba\xbe":
        raise ValueError("不是有效的 JVM class 文件")
    take(4)  # minor_version, major_version
    count = number()
    pool = [None] * count
    index = 1
    while index < count:
        tag = number(1)
        if tag == 1:
            encoded = take(number()).replace(b"\xc0\x80", b"\0")
            modified = encoded.decode("utf-8", "surrogatepass")
            value = modified.encode("utf-16-le", "surrogatepass").decode(
                "utf-16-le", "replace"
            )
        elif tag in (3, 4, 5, 6):
            value = take(8 if tag in (5, 6) else 4)
        elif tag in (7, 8, 16, 19, 20):
            value = number()
        elif tag in (9, 10, 11, 12, 17, 18):
            value = struct.unpack(">HH", take(4))
        elif tag == 15:
            value = (number(1), number())
        else:
            raise ValueError(f"未知 JVM 常量池 tag：{tag}")
        pool[index] = (tag, value)
        index += 2 if tag in (5, 6) else 1
    if index != count:
        raise ValueError("JVM 常量池槽数无效")

    def constant(slot, expected):
        if not 0 < slot < count or pool[slot] is None or pool[slot][0] != expected:
            raise ValueError("JVM 常量池索引无效")
        return pool[slot][1]

    def class_name(slot):
        return constant(constant(slot, 7), 1)

    def attributes():
        nonlocal offset
        for _ in range(number()):
            constant(number(), 1)
            size = number(4)
            offset += size
            if offset > len(raw):
                raise ValueError("class 属性内容不完整")

    take(2)  # access_flags
    owner = class_name(number())
    symbols = [("class", owner, "类声明")]
    if parent := number():
        symbols.append(("super_class", class_name(parent), "父类"))
    for _ in range(number()):
        symbols.append(("interface", class_name(number()), "接口"))
    for kind in ("field", "method"):
        for _ in range(number()):
            take(2)
            name, desc = constant(number(), 1), constant(number(), 1)
            symbols.append((kind, f"{owner}.{name}:{desc}", "成员声明"))
            attributes()
    attributes()
    if offset != len(raw):
        raise ValueError("class 文件有多余字节")
    for slot, item in enumerate(pool):
        if item is None:
            continue
        tag, value = item
        if tag == 1:
            symbols.append(("utf8", value, f"常量池 #{slot}"))
        elif tag in (7, 8):
            kind = "class_ref" if tag == 7 else "string"
            symbols.append((kind, constant(value, 1), f"常量池 #{slot}"))
        elif tag in (9, 10, 11):
            class_slot, member_slot = value
            name, desc = constant(member_slot, 12)
            symbol = f"{class_name(class_slot)}.{constant(name, 1)}:{constant(desc, 1)}"
            kind = "field_ref" if tag == 9 else "method_ref"
            symbols.append((kind, symbol, f"常量池 #{slot}"))
    return owner.replace("/", "."), symbols


def search_jar(path, args, limit):
    query = args["query"]
    if not query or not query.strip():
        raise ValueError("query 必须是非空字符串")
    try:
        pattern = re.compile(
            query if args.get("regex", False) else re.escape(query),
            0 if args.get("case_sensitive", False) else re.IGNORECASE,
        )
    except re.error as error:
        raise ValueError(f"query 正则无效：{error}") from error
    scope, glob = args.get("scope", "all"), args.get("glob", "*")
    result = {
        "matches": [],
        "matched_entries": 0,
        "total_hits": 0,
        "truncated": False,
        "scanned_classes": 0,
        "scanned_resources": 0,
        "nested_jars": [],
        "parse_errors": [],
    }
    budget = 6800

    def append(key, row):
        nonlocal budget
        size = len(json.dumps(row, ensure_ascii=False)) + 2
        if size > budget:
            result["truncated"] = True
            return
        budget -= size
        result[key].append(row)

    def scan(jar, entries, nested):
        for item in entries:
            name = item.filename
            if item.is_dir() or not fnmatchcase(name, glob):
                continue
            location = {"entry": name}
            if nested is not None:
                location["nested_jar"] = nested
            class_name = None
            if name.lower().endswith(".class") and scope != "resources":
                result["scanned_classes"] += 1
                try:
                    if item.file_size > 16 * MIB:
                        raise ValueError("单个 class 超过 16 MiB")
                    class_name, symbols = class_symbols(jar.read(item))
                except (ValueError, BadZipFile) as error:
                    if len(result["parse_errors"]) < 30:
                        append("parse_errors", {**location, "error": str(error)[:200]})
                    else:
                        result["truncated"] = True
                    continue
            elif scope != "classes" and not binary_entry(name):
                with jar.open(item) as stream:
                    raw = stream.read(2 * MIB)
                contents = raw.decode("utf-8-sig", "replace")
                if not is_text(contents):
                    continue
                if item.file_size > 2 * MIB:
                    result["truncated"] = True
                result["scanned_resources"] += 1
                symbols = (
                    ("resource", line, number)
                    for number, line in enumerate(contents.splitlines(), 1)
                )
            else:
                continue
            matched = False
            for kind, value, detail in symbols:
                if not (hit := pattern.search(value)):
                    continue
                result["total_hits"] += 1
                matched = True
                if len(result["matches"]) >= limit:
                    result["truncated"] = True
                    continue
                start = max(0, hit.start() - 90)
                snippet = value[start : start + 280]
                row = {
                    **location,
                    "kind": kind,
                    "class_name": class_name,
                    "match": snippet,
                    "detail": detail,
                }
                if kind == "resource":
                    row["line"] = detail
                append("matches", row)
            result["matched_entries"] += matched

    specified = args.get("nested_jar")
    with open_jar(path, specified) as (jar, entries):
        if specified is not None:
            append("nested_jars", specified)
        scan(jar, entries, specified)
        if specified is None and args.get("include_nested", False):
            bytes_left = JAR_BYTES - sum(i.file_size for i in entries)
            entries_left = JAR_ENTRIES - len(entries)
            for item in entries:
                name = item.filename
                if item.is_dir() or not name.lower().endswith(".jar"):
                    continue
                try:
                    with open_nested(jar, name) as inner:
                        files = checked_entries(
                            inner, bytes_left=bytes_left, entries_left=entries_left
                        )
                        bytes_left -= sum(i.file_size for i in files)
                        entries_left -= len(files)
                        append("nested_jars", name)
                        scan(inner, files, name)
                except ValueError as error:
                    if len(result["parse_errors"]) < 30:
                        append(
                            "parse_errors",
                            {"nested_jar": name, "error": str(error)[:200]},
                        )
                    else:
                        result["truncated"] = True
    return result


def clean_manifest(raw):
    main = []
    keep = False
    for line in re.split(rb"\r\n|\r|\n", raw):
        if not line:
            break
        if line.startswith(b" "):
            if keep:
                main.append(line)
            continue
        key = line.partition(b":")[0].lower()
        keep = key != b"signature-version" and not re.search(rb"-digest(?:-|$)", key)
        if keep:
            main.append(line)
    return b"\r\n".join([*main, b"", b""])
