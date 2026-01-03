"""
MADMIN Authentication Service

Business logic for authentication operations including:
- Password hashing and verification
- JWT token creation and validation
- User CRUD operations
"""
from datetime import datetime, timedelta
from typing import Optional, List
from passlib.context import CryptContext
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import uuid
import logging

from config import get_settings
from .models import User, Permission, UserPermission, UserCreate, UserUpdate, CORE_PERMISSIONS

logger = logging.getLogger(__name__)
settings = get_settings()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT Configuration
ALGORITHM = "HS256"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password for storage."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Payload data (typically {"sub": username, "user_id": uuid})
        expires_delta: Token lifetime. Defaults to settings value.
    
    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decode and validate a JWT token.
    
    Returns:
        Token payload dict if valid, None otherwise
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.warning(f"JWT decode error: {e}")
        return None


async def authenticate_user(session: AsyncSession, username: str, password: str) -> Optional[User]:
    """
    Authenticate a user by username and password.
    
    Returns:
        User object if authentication successful, None otherwise
    """
    result = await session.execute(
        select(User)
        .options(selectinload(User.permissions))
        .where(User.username == username)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    
    return user


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
    """Get a user by their UUID, including permissions."""
    result = await session.execute(
        select(User)
        .options(selectinload(User.permissions))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    """Get a user by username, including permissions."""
    result = await session.execute(
        select(User)
        .options(selectinload(User.permissions))
        .where(User.username == username)
    )
    return result.scalar_one_or_none()


async def get_all_users(session: AsyncSession) -> List[User]:
    """Get all users with their permissions."""
    result = await session.execute(
        select(User)
        .options(selectinload(User.permissions))
        .order_by(User.username)
    )
    return result.scalars().all()


async def create_user(session: AsyncSession, user_data: UserCreate) -> User:
    """
    Create a new user.
    
    Args:
        session: Database session
        user_data: User creation data
    
    Returns:
        Created User object
    
    Raises:
        ValueError: If username already exists
    """
    # Check if user exists
    existing = await get_user_by_username(session, user_data.username)
    if existing:
        raise ValueError(f"Username '{user_data.username}' already exists")
    
    user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        is_superuser=user_data.is_superuser
    )
    
    session.add(user)
    await session.flush()
    await session.refresh(user)
    
    return user


async def update_user(session: AsyncSession, user_id: uuid.UUID, user_data: UserUpdate) -> User:
    """
    Update an existing user.
    
    Args:
        session: Database session
        user_id: User UUID to update
        user_data: Update data
    
    Returns:
        Updated User object
    
    Raises:
        ValueError: If user not found
    """
    user = await get_user_by_id(session, user_id)
    if not user:
        raise ValueError("User not found")
    
    if user_data.password is not None:
        user.hashed_password = get_password_hash(user_data.password)
    if user_data.email is not None:
        user.email = user_data.email
    if user_data.is_active is not None:
        user.is_active = user_data.is_active
    if user_data.is_superuser is not None:
        user.is_superuser = user_data.is_superuser
    
    session.add(user)
    await session.flush()
    await session.refresh(user)
    
    return user


async def delete_user(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """
    Delete a user.
    
    Returns:
        True if deleted, False if not found
    """
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    
    await session.delete(user)
    return True


async def update_last_login(session: AsyncSession, user: User) -> None:
    """Update user's last login timestamp."""
    user.last_login = datetime.utcnow()
    session.add(user)


# --- Permission Management ---

async def get_all_permissions(session: AsyncSession) -> List[Permission]:
    """Get all registered permissions."""
    result = await session.execute(
        select(Permission).order_by(Permission.slug)
    )
    return result.scalars().all()


async def get_user_permissions(session: AsyncSession, user_id: uuid.UUID) -> List[str]:
    """Get list of permission slugs for a user."""
    user = await get_user_by_id(session, user_id)
    if not user:
        return []
    if user.is_superuser:
        # Return all permissions for superuser
        perms = await get_all_permissions(session)
        return [p.slug for p in perms]
    return [p.slug for p in user.permissions]


async def set_user_permissions(session: AsyncSession, user_id: uuid.UUID, permission_slugs: List[str]) -> User:
    """
    Set permissions for a user (replaces existing permissions).
    
    Args:
        session: Database session
        user_id: User UUID
        permission_slugs: List of permission slugs to assign
    
    Returns:
        Updated User object
    """
    user = await get_user_by_id(session, user_id)
    if not user:
        raise ValueError("User not found")
    
    # Clear existing permissions
    await session.execute(
        UserPermission.__table__.delete().where(UserPermission.user_id == user_id)
    )
    
    # Add new permissions
    for slug in permission_slugs:
        link = UserPermission(user_id=user_id, permission_slug=slug)
        session.add(link)
    
    await session.flush()
    
    # Refresh to get updated permissions
    return await get_user_by_id(session, user_id)


async def init_core_permissions(session: AsyncSession) -> None:
    """
    Initialize core permissions in database.
    Called during application startup.
    """
    for perm_data in CORE_PERMISSIONS:
        result = await session.execute(
            select(Permission).where(Permission.slug == perm_data["slug"])
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            permission = Permission(
                slug=perm_data["slug"],
                description=perm_data["description"],
                module_id=None  # Core permissions have no module
            )
            session.add(permission)
            logger.info(f"Created core permission: {perm_data['slug']}")
    
    await session.commit()


async def init_default_admin(session: AsyncSession) -> None:
    """
    Create default admin user if no users exist.
    Called during application startup.
    """
    result = await session.execute(select(User).limit(1))
    if result.scalar_one_or_none() is not None:
        return  # Users exist, skip
    
    admin = User(
        username="admin",
        email="admin@localhost",
        hashed_password=get_password_hash("admin"),
        is_superuser=True
    )
    session.add(admin)
    await session.commit()
    logger.info("Created default admin user (username: admin, password: admin)")
