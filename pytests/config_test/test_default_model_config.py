from apisource.aliyun.provider import _build_tier_mapping, _load_template

from src.config.config import ModelConfig
from src.config.default_model_config import create_default_model_config


def test_default_model_config_includes_qwen37_models() -> None:
    """默认配置应完整注册 Qwen 3.7 对话与向量模型。"""

    config = create_default_model_config(ModelConfig)
    models = {model.name: model for model in config.models}

    assert config.model_task_config.replyer.model_list[:2] == ["qwen3.7-flash", "qwen3.7-plus"]
    assert config.model_task_config.planner.model_list[:2] == ["qwen3.7-flash", "qwen3.7-plus"]
    assert config.model_task_config.utils.model_list[:2] == ["qwen3.7-flash", "qwen3.7-plus"]
    assert config.model_task_config.embedding.model_list == ["qwen3.7-text-embedding"]
    assert models["qwen3.7-flash"].model_identifier == "qwen3.7-flash"
    assert models["qwen3.7-plus"].model_identifier == "qwen3.7-plus"
    assert models["qwen3.7-text-embedding"].model_identifier == "qwen3.7-text-embedding"


def test_aliyun_tiers_include_qwen37_chat_and_embedding_models() -> None:
    """梯度方案应按档位分配 Qwen 对话模型，并固定使用同一个向量模型。"""

    template = _load_template()
    low = _build_tier_mapping(template, "low")
    high = _build_tier_mapping(template, "high")

    for slot in ("replyer", "planner", "utils"):
        assert low[slot] == ["qwen3.7-flash"]
        assert high[slot] == ["qwen3.7-plus", "qwen3.7-flash"]
    assert low["embedding"] == ["qwen3.7-text-embedding"]
    assert high["embedding"] == ["qwen3.7-text-embedding"]
