"""
MADMIN Authentication Router

API endpoints for authentication and user management.
"""
import json
from typing import List, Optional
from datetime import timedelta
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, Query
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
from .totp import (
    generate_totp_secret, generate_backup_codes,
    get_provisioning_uri, generate_qr_base64,
    verify_totp, verify_backup_code
)
from .dependencies import (
    get_current_user, 
    require_permission,
    require_superuser,
    oauth2_scheme
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
settings = get_settings()


# --- Pydantic models for 2FA ---

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class TwoFactorSetupResponse(BaseModel):
    secret: str
    qr_code: str
    backup_codes: List[str]

class TwoFactorVerifyRequest(BaseModel):
    code: str

class TwoFactorDisableRequest(BaseModel):
    password: str


@router.post("/token")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session)
):
    """
    OAuth2 compatible token login.
    Returns JWT access token on successful authentication.
    If 2FA is enabled, returns token_type='2fa_required' and a temporary token.
    """
    user = await service.authenticate_user(session, form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # If 2FA is enabled, return temporary token requiring OTP verification
    if user.totp_enabled:
        temp_token = service.create_access_token(
            data={"sub": user.username, "user_id": str(user.id), "2fa_pending": True},
            expires_delta=timedelta(minutes=5)
        )
        return {"access_token": temp_token, "token_type": "2fa_required"}
    
    # Update last login
    await service.update_last_login(session, user)
    await session.commit()
    
    # Create token
    access_token = service.create_access_token(
        data={"sub": user.username, "user_id": str(user.id)},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes)
    )
    
    return Token(access_token=access_token)


@router.post("/token/2fa", response_model=Token)
async def verify_2fa_login(
    code: str = Query(..., description="6-digit OTP code or backup code"),
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session)
):
    """
    Complete login with 2FA verification.
    Requires the temporary token from /token endpoint.
    """
    payload = service.decode_access_token(token)
    if not payload or not payload.get("2fa_pending"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired 2FA token"
        )
    
    user = await service.get_user_by_username(session, payload.get("sub"))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    # Verify TOTP code first
    if not verify_totp(user.totp_secret, code):
        # Try backup code
        valid, new_codes = verify_backup_code(user.backup_codes or "[]", code)
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid 2FA code"
            )
        # Update backup codes (one was used)
        user.backup_codes = new_codes
        session.add(user)
    
    # Update last login
    await service.update_last_login(session, user)
    await session.commit()
    
    # Create final access token
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
        totp_enabled=current_user.totp_enabled,
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
            totp_enabled=u.totp_enabled,
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
            totp_enabled=user.totp_enabled,
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
        totp_enabled=user.totp_enabled,
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
    
    # ADMIN PROTECTION: Only admin can modify the admin account
    if user.username == "admin" and current_user.username != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="L'account admin può essere modificato solo da admin stesso"
        )
    
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
            totp_enabled=updated_user.totp_enabled,
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
            totp_enabled=updated_user.totp_enabled,
            created_at=updated_user.created_at,
            last_login=updated_user.last_login,
            permissions=[p.slug for p in updated_user.permissions]
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# --- Self-Service Password Change ---

@router.post("/me/password")
async def change_own_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Change own password (requires current password verification).
    This endpoint allows any authenticated user to change their own password.
    """
    if not service.verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password attuale non corretta"
        )
    
    if len(data.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nuova password deve essere di almeno 6 caratteri"
        )
    
    await service.update_user(session, current_user.id, UserUpdate(password=data.new_password))
    await session.commit()
    
    return {"message": "Password aggiornata con successo"}


# --- 2FA Management ---

@router.get("/me/2fa/status")
async def get_2fa_status(
    current_user: User = Depends(get_current_user)
):
    """Get 2FA status for current user."""
    return {
        "enabled": current_user.totp_enabled,
        "has_backup_codes": bool(current_user.backup_codes and json.loads(current_user.backup_codes))
    }


@router.post("/me/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Start 2FA setup - generates secret and QR code.
    The user must verify a code with /me/2fa/enable to complete setup.
    """
    if current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA è già attiva. Disattivala prima di configurarla nuovamente."
        )
    
    secret = generate_totp_secret()
    backup_codes = generate_backup_codes()
    uri = get_provisioning_uri(secret, current_user.username)
    qr = generate_qr_base64(uri)
    
    # Store secret and backup codes (not enabled yet)
    current_user.totp_secret = secret
    current_user.backup_codes = json.dumps(backup_codes)
    session.add(current_user)
    await session.commit()
    
    return TwoFactorSetupResponse(
        secret=secret,
        qr_code=qr,
        backup_codes=backup_codes
    )


@router.post("/me/2fa/enable")
async def enable_2fa(
    data: TwoFactorVerifyRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Verify code and enable 2FA.
    Requires a valid TOTP code from the authenticator app.
    """
    if not current_user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prima esegui /me/2fa/setup per generare il secret"
        )
    
    if current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA è già attiva"
        )
    
    if not verify_totp(current_user.totp_secret, data.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Codice non valido. Verifica che l'ora del tuo dispositivo sia corretta."
        )
    
    current_user.totp_enabled = True
    session.add(current_user)
    await session.commit()
    
    return {"message": "2FA attivata con successo"}


@router.delete("/me/2fa/disable")
async def disable_2fa(
    data: TwoFactorDisableRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Disable 2FA (requires password verification).
    """
    if not current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA non è attiva"
        )
    
    if not service.verify_password(data.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password non corretta"
        )
    
    current_user.totp_secret = None
    current_user.totp_enabled = False
    current_user.backup_codes = None
    session.add(current_user)
    await session.commit()
    
    return {"message": "2FA disattivata"}


@router.post("/me/2fa/backup-codes")
async def regenerate_backup_codes(
    data: TwoFactorVerifyRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Regenerate backup codes (requires TOTP code verification).
    Returns a new set of 10 backup codes.
    """
    if not current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA non è attiva"
        )
    
    if not verify_totp(current_user.totp_secret, data.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Codice non valido"
        )
    
    backup_codes = generate_backup_codes()
    current_user.backup_codes = json.dumps(backup_codes)
    session.add(current_user)
    await session.commit()
    
    return {"backup_codes": backup_codes}


# --- User Edit Permission Check ---

@router.get("/users/{username}/can-edit")
async def can_edit_user(
    username: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Check if current user can edit target user.
    Used by frontend to show/hide edit buttons.
    """
    user = await service.get_user_by_username(session, username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    can_edit = True
    can_change_password = True
    can_delete = True
    
    # Self-edit: can only change password via /me/password
    if user.id == current_user.id:
        can_edit = current_user.has_permission("users.manage")
        can_change_password = True
        can_delete = False
    
    # Admin can only be modified by admin
    if user.username == "admin" and current_user.username != "admin":
        can_edit = False
        can_change_password = False
        can_delete = False
    
    # Must have users.manage to edit others
    if not current_user.has_permission("users.manage") and user.id != current_user.id:
        can_edit = False
        can_change_password = False
        can_delete = False
    
    return {
        "can_edit": can_edit,
        "can_change_password": can_change_password,
        "can_delete": can_delete
    }

