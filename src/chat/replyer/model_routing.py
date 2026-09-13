"""Planner 回复模型路由声明与候选校验。"""

from typing import Any, Dict, Optional

from src.config.config import config_manager


def build_reply_model_routing_schema() -> Optional[Dict[str, Any]]:
    """按当前配置生成 Planner 可见的路由规则与模型白名单。"""
    config = config_manager.get_model_config()
    task = config.model_task_config.replyer
    if not task.routing_prompt.strip():
        return None

    models = {model.name: model for model in config.models}
    candidates = list(dict.fromkeys(task.model_list))
    if not candidates:
        raise ValueError("供应商路由已开启，但回复模型池为空")
    catalog = "\n".join(f"- {name}：供应商 {models[name].api_provider}" for name in candidates)
    return {
        "type": "string",
        "enum": candidates,
        "description": (
            "可选。根据以下路由规则选择本次回复模型，填写模型名称。"
            "仅使用当前候选；同一供应商有多个模型时结合规则选择。"
            "规则未匹配时省略此参数，使用默认模型选择策略。\n"
            f"路由规则：\n{task.routing_prompt.strip()}\n候选模型：\n{catalog}"
        ),
    }


def resolve_reply_model(reply_tool_args: Dict[str, Any]) -> Optional[str]:
    """校验本次路由模型，关闭路由时忽略历史工具参数。"""
    config = config_manager.get_model_config()
    task = config.model_task_config.replyer
    if not task.routing_prompt.strip():
        return None
    selected = reply_tool_args.get("reply_model")
    if selected is None or selected == "":
        return None
    if not isinstance(selected, str):
        raise ValueError("reply_model 必须是回复模型池中的模型名称")
    if selected not in task.model_list or not any(model.name == selected for model in config.models):
        raise ValueError(f"路由模型 '{selected}' 不在当前回复模型池中")
    return selected
