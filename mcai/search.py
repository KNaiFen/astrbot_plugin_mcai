"""Codex standalone alpha/search, using the selected AstrBot provider transport."""

import uuid

from .review import digest


async def alpha_search(provider, session_id, arguments):
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
    result = await client.post("alpha/search", cast_to=dict[str, object], body=body)
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
        lambda: alpha_search(provider, session["id"], arguments),
        tasks.agent.attempts,
        pause_on_error=False,
    )
    tasks.store.save("search_result", call_id, result)
    tasks.log(job, "alpha_search", arguments=arguments, result=result)
    return result
