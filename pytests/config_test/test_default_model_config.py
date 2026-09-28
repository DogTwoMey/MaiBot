import tomlkit

from apisource import _common
from apisource.aliyun.provider import _build_tier_mapping, _load_template

from src.config.config import ModelConfig
from src.config.default_model_config import create_default_model_config


def test_default_model_config_includes_qwen37_models() -> None:
    """默认配置应完整注册 Qwen 3.7 对话与向量模型。"""

    config = create_default_model_config(ModelConfig)
    models = {model.name: model for model in config.models}

    assert config.model_task_config.replyer.model_list == ["qwen3.7-plus", "qwen3.8-flash", "deepseek-flash-think"]
    assert config.model_task_config.planner.model_list == ["qwen3.8-flash", "deepseek-flash"]
    assert config.model_task_config.utils.model_list == ["qwen3.7-flash", "deepseek-flash"]
    assert config.model_task_config.vlm.model_list == ["qwen3.8-flash"]
    assert config.model_task_config.voice.model_list == ["qwen3.8-omni-flash"]
    assert config.model_task_config.embedding.model_list == ["qwen3.7-text-embedding"]
    assert models["qwen3.7-flash"].model_identifier == "qwen3.7-flash"
    assert (models["qwen3.7-flash"].price_in, models["qwen3.7-flash"].price_out) == (0.2, 0.8)
    assert models["qwen3.7-plus"].model_identifier == "qwen3.7-plus"
    assert (models["qwen3.7-plus"].price_in, models["qwen3.7-plus"].price_out) == (2.0, 8.0)
    assert models["qwen3.7-text-embedding"].model_identifier == "qwen3.7-text-embedding"
    assert (models["qwen3.7-text-embedding"].price_in, models["qwen3.7-text-embedding"].price_out) == (0.5, 0.0)


def test_aliyun_tiers_include_qwen37_chat_and_embedding_models() -> None:
    """梯度方案应按档位分配 Qwen 对话模型，并固定使用同一个向量模型。"""

    template = _load_template()
    low = _build_tier_mapping(template, "low")
    high = _build_tier_mapping(template, "high")

    for slot in ("replyer", "planner", "utils"):
        assert low[slot] == ["qwen3.7-flash"]
    assert high["replyer"] == high["planner"] == ["qwen3.7-plus", "qwen3.8-flash"]
    assert high["utils"] == ["qwen3.7-flash"]
    assert high["voice"] == ["qwen3.8-omni-flash"]
    assert low["embedding"] == ["qwen3.7-text-embedding"]
    assert high["embedding"] == ["qwen3.7-text-embedding"]


def test_provider_bundle_preserves_instance_settings(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "model_config.toml"
    config_path.write_text('''
[[api_providers]]
name = "Example"
api_key = "local-key"
base_url = "https://local.test"
[[models]]
name = "model"
api_provider = "Example"
[model_task_config.replyer]
model_list = ["model"]
max_tokens = 777
temperature = 0.9
''', encoding="utf-8")
    before = tomlkit.loads(config_path.read_text(encoding="utf-8"))
    providers = tomlkit.aot()
    providers.append(tomlkit.item({"name": "Example", "api_key": "replacement", "base_url": "https://new.test"}))
    bundle = _common.ProviderBundle(
        models_aot=before["models"], providers_aot=providers, tier_mapping={"replyer": ["model"]},
        embedding_name="", tier="high", is_managed_provider_name=lambda name: name == "Example",
    )
    monkeypatch.setattr(_common, "CONFIG_PATH", config_path)
    monkeypatch.setattr(_common, "BACKUP_DIR", tmp_path / "backup")

    _common.apply_bundle_to_config(bundle)

    after = tomlkit.loads(config_path.read_text(encoding="utf-8"))
    assert after["api_providers"] == before["api_providers"]
    assert after["model_task_config"]["replyer"] == before["model_task_config"]["replyer"]
