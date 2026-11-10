from datetime import datetime, timedelta

import pytest

from src.chat.utils import statistic


def test_model_request_cache_rate_ignores_disabled_model_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型未开启 cache 时，其 prompt token 不进入缓存命中率分母。"""

    now = datetime.now()
    records = [
        {
            "timestamp": now,
            "request_type": "chat.reply",
            "model_api_provider_name": "provider",
            "model_assign_name": "cache-enabled",
            "model_name": "gpt-a",
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "prompt_cache_enabled": True,
            "prompt_cache_hit_tokens": 4,
            "prompt_cache_miss_tokens": 6,
            "cost": 0.01,
            "time_cost": 1.0,
            "session_id": "g_validation",
        },
        {
            "timestamp": now,
            "request_type": "chat.reply",
            "model_api_provider_name": "provider",
            "model_assign_name": "cache-disabled",
            "model_name": "gpt-b",
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "prompt_cache_enabled": False,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 10,
            "cost": 0.01,
            "time_cost": 1.0,
            "session_id": "",
        },
    ]
    monkeypatch.setattr(statistic, "fetch_model_usage_since", lambda query_start_time: records)

    stats = statistic.StatisticOutputTask._collect_model_request_for_period([("last_hour", now - timedelta(hours=1))])
    period_stats = stats["last_hour"]

    assert period_stats[statistic.TOTAL_REQ_CNT] == 2
    assert period_stats[statistic.IN_TOK_BY_MODEL]["cache-disabled"] == 10
    assert period_stats[statistic.CACHE_HIT_TOK] == 4
    assert period_stats[statistic.CACHE_MISS_TOK] == 6
    assert period_stats[statistic.CACHE_MISS_TOK_BY_MODEL]["cache-disabled"] == 0
    assert period_stats[statistic.COST_BY_CHAT]["g_validation"] == 0.01
    assert period_stats[statistic.COST_BY_CHAT][statistic.GLOBAL_COST_SESSION_KEY] == 0.01
    assert "" not in period_stats[statistic.COST_BY_CHAT]
