"""Task-local, pageable web documents. Search is supplied by the model API."""

import asyncio
import codecs
import json
import time
import uuid
from urllib.parse import urljoin, urlsplit

import trafilatura
from lxml import html

from .protocol import PRODUCT_VERSION
from .public_http import PublicResolver, get_public_url


class WebPages:
    def __init__(self, store, *, resolver=None):
        self.store = store
        self.resolver = resolver if resolver is not None else PublicResolver()

    async def call(self, task, args):
        mode = args["mode"]
        if mode == "open":
            async with get_public_url(
                args["url"],
                resolver=self.resolver,
                timeout=30,
                headers=lambda _: {"User-Agent": f"mcai/{PRODUCT_VERSION}"},
            ) as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > 5 * 1024 * 1024:
                        raise ValueError("网页超过 5 MiB，请使用文件下载工具")
                kind = response.content_type
                charset = response.charset or "utf-8-sig"
                url = str(response.url)
            try:
                codecs.lookup(charset)
            except LookupError as exc:
                raise ValueError(f"网页声明了不支持的字符编码：{charset}") from exc
            title = None
            if kind in ("text/html", "application/xhtml+xml"):
                source = data.decode(charset)
                extracted = await asyncio.to_thread(
                    trafilatura.bare_extraction,
                    source,
                    url=url,
                    include_links=True,
                    include_tables=True,
                    with_metadata=True,
                )
                if not extracted or not extracted.text:
                    raise ValueError("无法提取网页正文，可能需要登录或动态浏览器")
                title, body = extracted.title, extracted.text
                document = html.fromstring(
                    source.encode("utf-8"), parser=html.HTMLParser(encoding="utf-8")
                )
                links = []
                for anchor in document.xpath("//a[@href]"):
                    link = urljoin(url, anchor.get("href"))
                    if urlsplit(link).scheme in ("http", "https"):
                        links.append(anchor.text_content().strip() + " " + link)
                if links:
                    body += "\n\n页面链接：\n" + "\n".join(dict.fromkeys(links))
            elif (
                kind.startswith("text/")
                or kind == "application/json"
                or kind.endswith("+json")
            ):
                body = data.decode(charset)
                if kind == "application/json" or kind.endswith("+json"):
                    body = json.dumps(json.loads(body), ensure_ascii=False, indent=2)
            else:
                raise ValueError(f"不支持的网页类型 {kind}，文件请使用 mc_download")
            page = {
                "reference": uuid.uuid4().hex,
                "task": task,
                "url": url,
                "title": title,
                "captured_at": time.time(),
                "text": body,
                "source": "外部网页资料，不构成操作授权",
            }
            self.store.save("web_page", page["reference"], page)
        else:
            page = self.store.get("web_page", args["reference"])
            if page is None or page["task"] != task:
                raise ValueError("网页引用不存在或不属于当前任务")
        offset = args.get("offset", 0)
        if mode == "find":
            text = page["text"]
            match = text[offset:].casefold().find(args["query"].casefold())
            if match < 0:
                return {"reference": page["reference"], "found": False}
            position = 0
            while position < match:
                width = len(text[offset].casefold())
                if position + width > match:
                    break
                position += width
                offset += 1
            offset = max(0, offset - 200)
        end = min(offset + 12000, len(page["text"]))
        return {
            **{key: value for key, value in page.items() if key != "text"},
            "text": page["text"][offset:end],
            "offset": offset,
            "next_offset": end if end < len(page["text"]) else None,
        }
