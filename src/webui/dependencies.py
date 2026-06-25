from typing import Optional

from fastapi import Depends, Request

from .core import check_auth_rate_limit, get_auth_cookie_value, get_current_token, is_token_valid


async def require_auth(
    request: Request,
) -> str:
    """
    FastAPI 依赖：要求有效认证

    用于保护需要认证的路由，自动从 Cookie 获取并验证 token

    Returns:
        验证通过的 token

    Raises:
        HTTPException 401: 认证失败
    """
    return get_current_token(request)


async def require_auth_with_rate_limit(
    request: Request,
    _rate_limit: None = Depends(check_auth_rate_limit),
) -> str:
    """
    FastAPI 依赖：要求有效认证 + 频率限制

    组合了认证检查和频率限制，适用于敏感操作

    Returns:
        验证通过的 token

    Raises:
        HTTPException 401: 认证失败
        HTTPException 429: 请求过于频繁
    """
    return get_current_token(request)


def get_optional_token(
    request: Request,
) -> Optional[str]:
    """
    FastAPI 依赖：可选获取 token（不验证）

    用于某些需要知道是否有 token 但不强制验证的场景

    Returns:
        token 字符串或 None
    """
    return get_auth_cookie_value(request)


async def verify_token_optional(
    request: Request,
) -> bool:
    """
    FastAPI 依赖：可选验证 token

    返回 token 是否有效，不抛出异常

    Returns:
        True 如果 token 有效，否则 False
    """
    return is_token_valid(request)
