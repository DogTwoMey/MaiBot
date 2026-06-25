"""WebUI 认证模块。"""

from hashlib import sha256
from typing import Mapping, Optional

from fastapi import HTTPException, Request, Response

from src.common.logger import get_logger
from src.config.config import global_config

from .security import get_token_manager

logger = get_logger("webui.auth")

# Cookie 配置
LEGACY_COOKIE_NAME = "maibot_session"
COOKIE_NAME_PREFIX = "maibot_session"
COOKIE_NAME = LEGACY_COOKIE_NAME
COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7天
COOKIE_NAME_DIGEST_LENGTH = 16


def _is_secure_environment() -> bool:
    """
    检测是否应该启用安全 Cookie（HTTPS）

    Returns:
        bool: 如果应该使用 secure cookie 则返回 True
    """
    # 从配置读取
    if global_config.webui.secure_cookie:
        logger.info("配置中启用了 secure_cookie")
        return True

    # 检查是否是生产环境
    if global_config.webui.mode == "production":
        logger.info("WebUI运行在生产模式，启用 secure cookie")
        return True

    # 默认：开发环境不启用（因为通常是 HTTP）
    logger.debug("WebUI运行在开发模式，禁用 secure cookie")
    return False


def build_auth_cookie_name(token: str) -> str:
    """根据当前访问令牌生成实例隔离的认证 Cookie 名称。"""
    if not token:
        raise ValueError("访问令牌不能为空，无法生成认证 Cookie 名称")

    token_digest = sha256(token.encode("utf-8")).hexdigest()[:COOKIE_NAME_DIGEST_LENGTH]
    return f"{COOKIE_NAME_PREFIX}_{token_digest}"


def get_auth_cookie_name() -> str:
    """获取当前 MaiBot 进程应读取的认证 Cookie 名称。"""
    token_manager = get_token_manager()
    return build_auth_cookie_name(token_manager.get_token())


def get_auth_cookie_value_from_cookies(cookies: Mapping[str, str]) -> Optional[str]:
    """从 Cookie 映射中读取当前 MaiBot 进程专属的认证 token。"""
    return cookies.get(get_auth_cookie_name())


def get_auth_cookie_value(request: Request) -> Optional[str]:
    """从 FastAPI 请求中读取当前 MaiBot 进程专属的认证 token。"""
    return get_auth_cookie_value_from_cookies(request.cookies)


def _resolve_auth_source(auth_source: Optional[str] | Request) -> Optional[str]:
    """兼容 token 字符串和 Request 对象两类认证来源。"""
    if isinstance(auth_source, Request):
        return get_auth_cookie_value(auth_source)
    return auth_source


def get_current_token(request: Request) -> str:
    """
    获取当前请求的 token，仅从 HttpOnly Cookie 获取。

    Args:
        request: FastAPI Request 对象

    Returns:
        验证通过的 token

    Raises:
        HTTPException: 认证失败时抛出 401 错误
    """
    maibot_session = get_auth_cookie_value(request)
    if not is_token_valid(maibot_session):
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    assert maibot_session is not None
    return maibot_session


def is_token_valid(auth_source: Optional[str] | Request) -> bool:
    """判断认证 token 是否存在且有效。"""
    maibot_session = _resolve_auth_source(auth_source)
    if not maibot_session:
        return False

    token_manager = get_token_manager()
    return token_manager.verify_token(maibot_session)


def set_auth_cookie(response: Response, token: str, request: Optional[Request] = None) -> None:
    """
    设置认证 Cookie

    Args:
        response: FastAPI Response 对象
        token: 要设置的 token
        request: FastAPI Request 对象（可选，用于检测协议）
    """
    # 根据环境和实际请求协议决定安全设置
    is_secure = _is_secure_environment()

    # 如果提供了 request，检测实际使用的协议
    if request:
        # 检查 X-Forwarded-Proto header（代理/负载均衡器）
        forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
        if forwarded_proto:
            is_https = forwarded_proto == "https"
            logger.debug(f"检测到 X-Forwarded-Proto: {forwarded_proto}, is_https={is_https}")
        else:
            # 检查 request.url.scheme
            is_https = request.url.scheme == "https"
            logger.debug(f"检测到 scheme: {request.url.scheme}, is_https={is_https}")

        # 如果是 HTTP 连接，强制禁用 secure 标志
        if not is_https and is_secure:
            logger.warning("=" * 80)
            logger.warning("检测到 HTTP 连接但环境配置要求 HTTPS (secure cookie)")
            logger.warning("已自动禁用 secure 标志以允许登录，但建议修改配置：")
            logger.warning("1. 在配置文件中设置: webui.secure_cookie = false")
            logger.warning("2. 如果使用反向代理，请确保正确配置 X-Forwarded-Proto 头")
            logger.warning("=" * 80)
            is_secure = False

    # 设置当前 token 专属 Cookie，并清理旧版固定名称 Cookie，避免同域多实例互相覆盖。
    cookie_name = build_auth_cookie_name(token)
    response.delete_cookie(
        key=LEGACY_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )
    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,  # 防止 JS 读取，阻止 XSS 窃取
        samesite="lax",  # 使用 lax 以兼容更多场景（开发和生产）
        secure=is_secure,  # 根据实际协议决定
        path="/",  # 确保 Cookie 在所有路径下可用
    )

    logger.info(
        f"已设置认证 Cookie: {cookie_name}={token[:8]}... "
        f"(secure={is_secure}, samesite=lax, httponly=True, path=/, max_age={COOKIE_MAX_AGE})"
    )
    logger.debug(f"完整 token 前缀: {token[:20]}...")


def clear_auth_cookie(response: Response) -> None:
    """
    清除认证 Cookie

    Args:
        response: FastAPI Response 对象
    """
    # 保持与 set_auth_cookie 相同的安全设置
    is_secure = _is_secure_environment()

    for cookie_name in (get_auth_cookie_name(), LEGACY_COOKIE_NAME):
        response.delete_cookie(
            key=cookie_name,
            httponly=True,
            samesite="lax",
            secure=is_secure,
            path="/",
        )
    logger.debug("已清除认证 Cookie")


def verify_auth_token_from_cookie_or_header(
    auth_source: Optional[str] | Request = None,
) -> bool:
    """
    验证认证 Cookie。

    Args:
        auth_source: Cookie 中的 token 或 FastAPI Request 对象

    Returns:
        验证成功返回 True

    Raises:
        HTTPException: 认证失败时抛出 401 错误
    """
    if not is_token_valid(auth_source):
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    return True
