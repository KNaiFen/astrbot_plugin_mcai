"""Install and explicitly update the four user-owned runtime rule files."""

import os
import time
from datetime import UTC, datetime
from difflib import unified_diff
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from .protocol import PRODUCT_VERSION

TEMPLATES = {
    name: Path(__file__).with_name(source)
    for name, source in (
        ("AGENTS.md", "agent_rules.md"),
        ("REVIEW_AGENTS.md", "review_rules.md"),
        ("SUMMARY_AGENTS.md", "summary_rules.md"),
        ("CYBER_AGENTS.md", "cyber_rules.md"),
    )
}
BASELINE = "rule_baseline"


def save_baseline(store, name, template_sha256):
    store.save(
        BASELINE,
        name,
        {
            "template_sha256": template_sha256,
            "installed_at": time.time(),
            "product_version": PRODUCT_VERSION,
        },
    )


def rule_status(store, name, template, current):
    template_sha256 = sha256(template).hexdigest()
    file_sha256 = sha256(current).hexdigest() if current is not None else None
    baseline = store.get(BASELINE, name)
    modified = None
    if baseline is None:
        status = "unknown"
    else:
        original = baseline["template_sha256"]
        modified = file_sha256 != original
        status = (
            "latest"
            if original == template_sha256
            else "modified"
            if modified
            else "unmodified"
        )
    return {
        "status": status,
        "update_available": status != "latest",
        "modified": modified,
        "baseline": baseline,
        "template_sha256": template_sha256,
        "file_sha256": file_sha256,
    }


def install_rules(store):
    for name, source in TEMPLATES.items():
        target = store.directory / name
        if not target.exists():
            template = source.read_bytes()
            with target.open("xb") as stream:
                stream.write(template)
            save_baseline(store, name, sha256(template).hexdigest())
    for name, status in rules_status(store).items():
        if status["update_available"]:
            store.log("rule_template_available", name=name, **status)


def rules_status(store):
    states = {}
    for name, source in TEMPLATES.items():
        try:
            current = (store.directory / name).read_bytes()
        except FileNotFoundError:
            current = None
        states[name] = rule_status(store, name, source.read_bytes(), current)
    return states


def change_rule(store, name, action, expected_template=None, expected_file=None):
    if name not in TEMPLATES:
        raise ValueError("未知的运行时规则文件")
    target = store.directory / name
    source = TEMPLATES[name]
    template, current = source.read_bytes(), target.read_bytes()
    if action == "diff":
        lines = unified_diff(
            current.decode("utf-8-sig").splitlines(keepends=True),
            template.decode("utf-8-sig").splitlines(keepends=True),
            fromfile=name,
            tofile=source.name,
        )
        return {
            "diff": "".join(
                line
                if line.endswith("\n")
                else line + "\n\\ No newline at end of file\n"
                for line in lines
            )
        }
    if action not in ("adopt", "merged"):
        raise ValueError("未知的运行时规则操作")
    status = rule_status(store, name, template, current)
    if expected_template != status["template_sha256"] or (
        action == "adopt" and expected_file != status["file_sha256"]
    ):
        raise ValueError("规则或模板已变化，请刷新设置页后重新确认")
    result = {}
    if action == "adopt":
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = target.with_name(f"{target.stem}.bak-{stamp}.md")
        with backup.open("xb") as stream:
            stream.write(current)
        with NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            temporary.write_bytes(template)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        result["backup"] = backup.name
    save_baseline(store, name, status["template_sha256"])
    return result
