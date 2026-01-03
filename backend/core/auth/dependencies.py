"""
MADMIN Authentication Dependencies

FastAPI dependencies for authentication and authorization.
Use these in route handlers to protect endpoints.
"""
from typing import Optional, List, Callable
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from core.database import get_session
from .models import User, TokenData
from . import service

# OAuth2 scheme for Bearer token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session)
) -> User:
    """
    Dependency to get the current authenticated user.
    
    Validates the JWT token and returns the User object.
    Raises 401 Unauthorized if token is invalid or user not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = service.decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    username: str = payload.get("sub")
    user_id_str: str = payload.get("user_id")
    
    if username is None or user_id_str is None:
        raise credentials_exception
    
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise credentials_exception
    
    user = await service.get_user_by_id(session, user_id)
    
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Alias for get_current_user that ensures user is active."""
    return current_user


def require_permission(permission_slug: str) -> Callable:
    """
    Dependency factory that requires a specific permission.
    
    Usage:
        @router.get("/protected")
        async def protected_route(user: User = Depends(require_permission("users.manage"))):
            ...
    """
    async def permission_checker(
        current_user: User = Depends(get_current_user)
    ) -> User:
        if not current_user.has_permission(permission_slug):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied. Required: {permission_slug}"
            )
        return current_user
    
    return permission_checker


def require_any_permission(permission_slugs: List[str]) -> Callable:
    """
    Dependency factory that requires any of the specified permissions.
    
    Usage:
        @router.get("/protected")
        async def protected_route(
            user: User = Depends(require_any_permission(["users.view", "users.manage"]))
        ):
            ...
    """
    async def permission_checker(
        current_user: User = Depends(get_current_user)
    ) -> User:
        if not current_user.has_any_permission(permission_slugs):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied. Required one of: {', '.join(permission_slugs)}"
            )
        return current_user
    
    return permission_checker


def require_superuser() -> Callable:
    """
    Dependency factory that requires superuser status.
    
    Usage:
        @router.delete("/dangerous")
        async def dangerous_route(user: User = Depends(require_superuser())):
            ...
    """
    async def superuser_checker(
        current_user: User = Depends(get_current_user)
    ) -> User:
        if not current_user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Superuser access required"
            )
        return current_user
    
    return superuser_checker
