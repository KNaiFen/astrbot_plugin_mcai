"""Persistent request usage; separate from context budget calibration."""

import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


class UsageWriteError(RuntimeError):
    pass


def parse_prices(lines):
    prices = {}
    for line in lines:
        try:
            provider, rates = line.split("=", 1)
            currency, incoming, outgoing, cached = rates.split(":")
            amounts = tuple(Decimal(value) for value in (incoming, outgoing, cached))
            if (
                not provider
                or not currency
                or provider in prices
                or any(not value.is_finite() or value < 0 for value in amounts)
            ):
                raise ValueError
        except (AttributeError, ValueError, InvalidOperation) as exc:
            raise ValueError(
                "模型单价须按“提供商ID=货币:输入:输出:缓存”填写，每项为非负单价，提供商不能重复"
            ) from exc
        prices[provider] = (currency, *amounts)
    return prices


def totals(rows):
    return {
        key: sum(row[key] for row in rows)
        for key in (
            "requests",
            "input_tokens",
            "output_tokens",
            "cached_tokens",
            "cache_missing",
            "no_usage",
        )
    }


def record_request(store, task, stage, provider, model, usage):
    usage = usage or {}
    incoming = usage.get("input_tokens", usage.get("prompt_tokens", usage.get("input")))
    outgoing = usage.get(
        "output_tokens", usage.get("completion_tokens", usage.get("output"))
    )
    details = (
        usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    )
    cached = details.get("cached_tokens", usage.get("prompt_cache_hit_tokens"))
    if "input_other" in usage:
        cached = usage["input_cached"]
        incoming = usage["input_other"] + cached
    known = incoming is not None and outgoing is not None
    increment = {
        "requests": 1,
        "input_tokens": incoming or 0,
        "output_tokens": outgoing or 0,
        "cached_tokens": cached or 0,
        "cache_missing": int(cached is None),
        "no_usage": int(not known),
    }
    today = date.today().isoformat()
    day_key = json.dumps([today, provider, model], ensure_ascii=False)
    daily = store.get("model_usage_day", day_key)
    rows = [
        (
            "model_usage_day",
            day_key,
            {
                "date": today,
                "provider": provider,
                "model": model,
                **totals([daily, increment] if daily else [increment]),
            },
        )
    ]
    if task is not None:
        entries = store.get("model_usage_task", task) or {}
        key = json.dumps([stage, provider, model], ensure_ascii=False)
        entries[key] = {
            "purpose": stage,
            "provider": provider,
            "model": model,
            **totals([entries[key], increment] if key in entries else [increment]),
        }
        rows.append(("model_usage_task", task, entries))
    store.save_many(*rows)


def cost(rows, prices):
    amounts = {}
    if prices:
        for row in rows:
            price = prices.get(row["provider"])
            if price is None or row["requests"] == row["no_usage"]:
                continue
            currency, incoming, outgoing, cached = price
            amount = (
                (row["input_tokens"] - row["cached_tokens"]) * incoming
                + row["output_tokens"] * outgoing
                + row["cached_tokens"] * cached
            ) / 1000000
            amounts[currency] = amounts.get(currency, 0) + amount
    return [f"{currency} {amount:.6f}" for currency, amount in sorted(amounts.items())]


def task_usage(store, task, prices=None):
    entries = list((store.get("model_usage_task", task) or {}).values())
    return {
        **totals(entries),
        "review_requests": sum(
            row["requests"]
            for row in entries
            if row["purpose"] in ("审核模型", "审核历史压缩")
        ),
        "cost": cost(entries, prices),
    }


def usage_report(store, prices):
    cutoff = (date.today() - timedelta(days=29)).isoformat()
    daily = sorted(
        (row for row in store.all("model_usage_day") if row["date"] >= cutoff),
        key=lambda row: (row["date"], row["provider"], row["model"]),
        reverse=True,
    )
    tasks = [
        {
            "name": row["name"],
            "group": row["group"],
            **task_usage(store, row["id"], prices),
        }
        for row in store.all("task")
    ]
    tasks = sorted(
        (row for row in tasks if row["requests"]),
        key=lambda row: row["input_tokens"] + row["output_tokens"],
        reverse=True,
    )
    return {
        "daily": [{**row, "cost": cost([row], prices)} for row in daily],
        "tasks": tasks[:10],
    }
