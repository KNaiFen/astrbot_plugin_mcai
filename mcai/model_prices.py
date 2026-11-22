import math
import time

import aiohttp

UPSTREAM_MODEL_PRICE_URLS = (
    "https://models.dev/api.json",
    "https://models.opencode.ai/api.json",
)


def priced_models(data):
    if not isinstance(data, dict):
        raise ValueError("上游价格目录不是 JSON 对象")
    items = []
    for provider_id, provider in data.items():
        if not isinstance(provider, dict) or not isinstance(
            provider.get("models"), dict
        ):
            continue
        provider_name = provider.get("name")
        for model_id, model in provider["models"].items():
            rates = model.get("cost") if isinstance(model, dict) else None
            if not isinstance(rates, dict):
                continue
            cache = rates.get("cache_read")
            prices = (
                rates.get("input"),
                rates.get("output"),
                0 if cache is None else cache,
            )
            if not all(
                type(value) in (int, float) and 0 <= value < math.inf
                for value in prices
            ):
                continue
            identity, title = model.get("id"), model.get("name")
            items.append(
                {
                    "provider": provider_id,
                    "provider_name": provider_name
                    if isinstance(provider_name, str) and provider_name
                    else provider_id,
                    "model": identity
                    if isinstance(identity, str) and identity
                    else model_id,
                    "name": title if isinstance(title, str) and title else model_id,
                    "input": prices[0],
                    "output": prices[1],
                    "cache": prices[2],
                }
            )
    if not items:
        raise ValueError("上游目录没有有效的模型单价")
    return items


async def sync_upstream_prices(store):
    errors = []
    async with aiohttp.ClientSession(
        trust_env=True, timeout=aiohttp.ClientTimeout(total=25)
    ) as session:
        for url in UPSTREAM_MODEL_PRICE_URLS:
            try:
                async with session.get(url) as response:
                    response.raise_for_status()
                    items = priced_models(await response.json(content_type=None))
            except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                errors.append(f"{url}: {exc}")
                continue
            catalog = {
                "updated_at": time.time(),
                "source": url,
                "count": len(items),
                "models": items,
            }
            store.save("model_catalog", "latest", catalog)
            return catalog
    raise ValueError("上游模型价格同步失败：" + "；".join(errors))
