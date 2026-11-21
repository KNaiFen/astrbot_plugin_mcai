"""Codex standalone alpha/search, using the selected AstrBot provider transport."""

import re
import uuid
from functools import partial
from urllib.parse import urlsplit

from .review import digest
from .tracing import trace_calls


async def alpha_search(provider, session_id, arguments, *, store=None, task=None):
    if provider.provider_config.get("type") not in (
        "openai_chat_completion",
        "openai_responses",
    ):
        raise ValueError("独立搜索需要 OpenAI 兼容 Chat／Responses 提供商")
    mode = arguments["mode"]
    if mode == "search":
        command = {
            "search_query": [
                {
                    "q": arguments["query"],
                    **(
                        {"domains": arguments["domains"]}
                        if arguments.get("domains")
                        else {}
                    ),
                }
            ]
        }
    elif mode == "open":
        command = {
            "open": [
                {
                    "ref_id": arguments["reference"],
                    **({"lineno": arguments["line"]} if "line" in arguments else {}),
                }
            ]
        }
    else:
        command = {
            "find": [
                {"ref_id": arguments["reference"], "pattern": arguments["pattern"]}
            ]
        }
    command["response_length"] = "short"
    body = {"id": session_id, "model": provider.get_model(), "commands": command}
    client = provider.client.with_options(max_retries=0)
    post = partial(client.post, "alpha/search", cast_to=dict[str, object])
    if store is not None:
        post = trace_calls(provider, store, task, "独立搜索")(post, "alpha/search")
    result = await post(body=body)
    if not isinstance(result.get("output"), str) or not result["output"].strip():
        raise ValueError("独立搜索未返回可读 output，无法把加密内容用作搜索结果")
    return {"output": result["output"], "results": result.get("results", [])}


async def task_search(tasks, job, provider, arguments, call_id):
    previous = tasks.store.get("search_result", call_id)
    if previous:
        return previous
    identity = digest(
        {
            "provider": provider.provider_config["id"],
            "model": provider.get_model(),
            "base": str(provider.client.base_url),
        }
    )
    session = tasks.store.get("search_session", job["id"])
    if session and session["identity"] != identity and arguments["mode"] != "search":
        raise ValueError("搜索提供商或模型已改变，请重新搜索取得当前来源引用")
    if session is None or session["identity"] != identity:
        session = {"identity": identity, "id": uuid.uuid4().hex}
        tasks.store.save("search_session", job["id"], session)
    from .agent_runtime import model_request

    result = await model_request(
        tasks,
        job,
        "独立搜索",
        lambda: alpha_search(
            provider, session["id"], arguments, store=tasks.store, task=job["id"]
        ),
        tasks.agent.attempts,
        pause_on_error=False,
    )
    sources = session.setdefault("sources", {})
    for source in result["results"]:
        if source.get("ref_id") and urlsplit(source.get("url", "")).scheme in (
            "http",
            "https",
        ):
            sources[source["ref_id"]] = {
                "url": source["url"],
                "title": source.get("title", ""),
            }
    tasks.store.save("search_session", job["id"], session)
    tasks.store.save("search_result", call_id, result)
    tasks.log(job, "alpha_search", arguments=arguments, result=result)
    return result


def render_citations(store, task, text):
    if "cite" not in text:
        return text
    sources = (store.get("search_session", task) or {}).get("sources", {})
    used = {}

    def replace(match):
        labels = []
        for reference in match.group(1).split(""):
            source = sources.get(reference)
            if source is None:
                labels.append(f"[来源未解析：{reference}]")
                continue
            url = source["url"]
            if url not in used:
                used[url] = (len(used) + 1, source["title"])
            labels.append(f"[来源{used[url][0]}]")
        return "".join(dict.fromkeys(labels))

    text = re.sub(r"cite(.*?)", replace, text)
    if used:
        text += "\n来源：\n" + "\n".join(
            f"[{number}] {title} {url}" for url, (number, title) in used.items()
        )
    return text
