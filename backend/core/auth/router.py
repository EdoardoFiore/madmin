"""
MADMIN Authentication Router

API endpoints for authentication and user management.
"""
from typing import List
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from config import get_settings
from .models import (
    Token, 
    UserCreate, 
    UserUpdate, 
    UserResponse, 
    PermissionResponse,
    User
)
from . import service
from .dependencies import (
    get_current_user, 
    require_permission,
    require_superuser
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
settings = get_settings()


@router.post("/token", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session)
):
    """
    OAuth2 compatible token login.
    Returns JWT access token on successful authentication.
    """
    user = await service.authenticate_user(session, form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Update last login
    await service.update_last_login(session, user)
    await session.commit()
    
    # Create token
    access_token = service.create_access_token(
        data={"sub": user.username, "user_id": str(user.id)},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes)
    )
    
    return Token(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """Get current authenticated user information."""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        is_active=current_user.is_active,
        is_superuser=current_user.is_superuser,
        created_at=current_user.created_at,
        last_login=current_user.last_login,
        permissions=[p.slug for p in current_user.permissions] if not current_user.is_superuser else ["*"]
    )


# --- User Management ---

@router.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user: User = Depends(require_permission("users.view")),
    session: AsyncSession = Depends(get_session)
):
    """List all users (requires users.view permission)."""
    users = await service.get_all_users(session)
    return [
        UserResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            is_active=u.is_active,
            is_superuser=u.is_superuser,
            created_at=u.created_at,
            last_login=u.last_login,
            permissions=[p.slug for p in u.permissions]
        )
        for u in users
    ]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(require_permission("users.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Create a new user (requires users.manage permission)."""
    try:
        user = await service.create_user(session, user_data)
        await session.commit()
        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            created_at=user.created_at,
            last_login=user.last_login,
            permissions=[]
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/users/{username}", response_model=UserResponse)
async def get_user(
    username: str,
    current_user: User = Depends(require_permission("users.view")),
    session: AsyncSession = Depends(get_session)
):
    """Get a specific user by username."""
    user = await service.get_user_by_username(session, username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        created_at=user.created_at,
        last_login=user.last_login,
        permissions=[p.slug for p in user.permissions]
    )


@router.patch("/users/{username}", response_model=UserResponse)
async def update_user(
    username: str,
    user_data: UserUpdate,
    current_user: User = Depends(require_permission("users.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Update a user (requires users.manage permission)."""
    user = await service.get_user_by_username(session, username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    # Prevent non-superusers from creating superusers
    if user_data.is_superuser and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superusers can grant superuser status"
        )
    
    try:
        updated_user = await service.update_user(session, user.id, user_data)
        await session.commit()
        return UserResponse(
            id=updated_user.id,
            username=updated_user.username,
            email=updated_user.email,
            is_active=updated_user.is_active,
            is_superuser=updated_user.is_superuser,
            created_at=updated_user.created_at,
            last_login=updated_user.last_login,
            permissions=[p.slug for p in updated_user.permissions]
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/users/{username}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    username: str,
    current_user: User = Depends(require_permission("users.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Delete a user (requires users.manage permission)."""
    user = await service.get_user_by_username(session, username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    # Prevent self-deletion
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    await service.delete_user(session, user.id)
    await session.commit()


# --- Permission Management ---

@router.get("/permissions", response_model=List[PermissionResponse])
async def list_permissions(
    current_user: User = Depends(require_permission("permissions.manage")),
    session: AsyncSession = Depends(get_session)
):
    """List all available permissions."""
    permissions = await service.get_all_permissions(session)
    return [
        PermissionResponse(slug=p.slug, description=p.description, module_id=p.module_id)
        for p in permissions
    ]


@router.put("/users/{username}/permissions", response_model=UserResponse)
async def set_user_permissions(
    username: str,
    permission_slugs: List[str],
    current_user: User = Depends(require_permission("permissions.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Set permissions for a user (replaces existing permissions)."""
    user = await service.get_user_by_username(session, username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    # Cannot modify superuser permissions (they have all permissions implicitly)
    if user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify permissions for superuser accounts"
        )
    
    try:
        updated_user = await service.set_user_permissions(session, user.id, permission_slugs)
        await session.commit()
        return UserResponse(
            id=updated_user.id,
            username=updated_user.username,
            email=updated_user.email,
            is_active=updated_user.is_active,
            is_superuser=updated_user.is_superuser,
            created_at=updated_user.created_at,
            last_login=updated_user.last_login,
            permissions=[p.slug for p in updated_user.permissions]
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
