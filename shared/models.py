from datetime import datetime, timezone
from enum import Enum
from typing import LiteralString, TYPE_CHECKING
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Enum as SQLEnum, BigInteger, Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database import Base

if TYPE_CHECKING:
    from shared.models import ImageProcessingJob


class UserTier(str, Enum):
    FREE = "free"
    PREMIUM = "premium"
    ADMIN = "admin"


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class UserStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    SUSPENDED = "suspended"


class User(Base):
    # Primary identifiers
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
        index=True,
        comment="Telegram user ID"
    )

    # User profile information
    username: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)

    # Subscription and quota management
    tier: Mapped[UserTier] = mapped_column(
        SQLEnum(UserTier),
        default=UserTier.FREE,
        nullable=False,
        index=True
    )
    quota_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quota_limit: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    # Status and permissions
    status: Mapped[UserStatus] = mapped_column(
        SQLEnum(UserStatus),
        default=UserStatus.ACTIVE,
        nullable=False,
        index=True
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    jobs: Mapped[list["ImageProcessingJob"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    # Computed properties
    @property
    def full_name(self) -> LiteralString | str | None:
        """Generate full name from first and last name"""
        parts = [self.first_name, self.last_name]
        return " ".join(filter(None, parts)) or self.username or f"User {self.telegram_id}"

    @full_name.setter
    def full_name(self, value):
        self._full_name = value

    @property
    def is_active(self) -> bool:
        """Check if user is active"""
        return self.status == UserStatus.ACTIVE

    @is_active.setter
    def is_active(self, value):
        self._is_active = value

    @property
    def is_blocked(self) -> bool:
        """Check if user is blocked"""
        return self.status == UserStatus.BLOCKED

    @property
    def quota_percentage(self) -> float:
        """Calculate quota usage percentage"""
        if self.quota_limit == 0:
            return 0.0
        return (self.quota_used / self.quota_limit) * 100

    @property
    def is_quota_exceeded(self) -> bool:
        """Check if user has exceeded quota"""
        return self.quota_used >= self.quota_limit

    def __repr__(self) -> str:
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username={self.username})>"

    def __str__(self) -> LiteralString | str | None:
        return self.full_name


class ImageProcessingJob(Base):
    id: Mapped[PyUUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    processed_file_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[ProcessingStatus] = mapped_column(SQLEnum(ProcessingStatus), default=ProcessingStatus.PENDING, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_options: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    processing_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="jobs")