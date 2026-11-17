"""Lightweight character estimates calibrated by completed API input usage."""

import math

from astrbot.core.agent.context.token_counter import EstimateTokenCounter
from astrbot.core.agent.message import Message

from .review import digest

# Real 2026-11-16 benchmarks: summary 294090 / 187935 = 1.565;
# 102 main requests had a maximum ratio 1.377. Other purposes start at 1.6.
BASELINE_FACTORS = {
    "main": 1.4,
    "compaction": 1.6,
    "review": 1.6,
    "review_compaction": 1.6,
    "archive": 1.6,
}


def tokens(messages):
    return EstimateTokenCounter().count_tokens(
        [Message.model_validate(item) for item in messages]
    )


def calibration_key(provider, purpose):
    config = provider.provider_config
    return digest(
        {
            "provider": config.get("id"),
            "type": config.get("type"),
            "model": getattr(provider, "model_name", config.get("model")),
            "parameters": config.get("custom_extra_body", {}),
            "purpose": purpose,
        }
    )


def budget_factor(store, provider, purpose):
    sample = store.get("token_budget", calibration_key(provider, purpose))
    return sample["factor"] if sample else BASELINE_FACTORS[purpose]


def estimated_input(store, provider, purpose, estimate):
    baseline = BASELINE_FACTORS[purpose]
    sample = store.get("token_budget", calibration_key(provider, purpose))
    if sample is None:
        return math.ceil(estimate * baseline)
    # Calibrate the measured excess separately: a small request's high ratio
    # must not multiply a provider's fixed input overhead on larger requests.
    overheads = sample.get(
        "overheads",
        [sample["input_tokens"] - sample["estimated_tokens"] * baseline],
    )
    return math.ceil(estimate * baseline + max(0, max(overheads)) * 1.05)


def record_usage(store, provider, purpose, estimate, response):
    usage = response.usage
    if usage is None or usage.input <= 0:
        return
    key = calibration_key(provider, purpose)
    previous = store.get("token_budget", key)
    ratios = [*(previous or {}).get("ratios", []), usage.input / max(1, estimate)][-16:]
    overheads = [
        *(previous or {}).get("overheads", []),
        max(0, usage.input - estimate * BASELINE_FACTORS[purpose]),
    ][-16:]
    store.save(
        "token_budget",
        key,
        {
            "purpose": purpose,
            "estimated_tokens": estimate,
            "input_tokens": usage.input,
            "factor": max(
                BASELINE_FACTORS[purpose],
                max(ratios) * 1.05,
            ),
            "ratios": ratios,
            "overheads": overheads,
            "samples": (previous["samples"] if previous else 0) + 1,
        },
    )
