import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import UUID, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base


class ChatThread(Base):
    __tablename__ = "chat_thread"

    id: Mapped[int] = mapped_column("id", autoincrement=True, nullable=False, unique=True, primary_key=True, init=False)
    thread_title: Mapped[str] = mapped_column(String(63206))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Relationship to Chat
    chats: Mapped[list["Chat"]] = relationship("Chat", back_populates="thread", lazy="select", init=False)


class Chat(Base):
    __tablename__ = "chat"

    # --- no defaults (required args) ---
    id: Mapped[int] = mapped_column("id", autoincrement=True, nullable=False, unique=True, primary_key=True, init=False)
    user_prompt: Mapped[str] = mapped_column(String(63206))
    final_prompt: Mapped[str] = mapped_column(String(63206))
    llm_response: Mapped[str] = mapped_column(String(63206))
    status: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(63206))
    provider: Mapped[str] = mapped_column(String(63206))
    role: Mapped[str] = mapped_column(String(100))

    # --- defaults after ---
    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), default_factory=uuid7, unique=True)
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("chat_thread.id"), index=True, default=None)
    total_tokens: Mapped[int | None] = mapped_column(Integer(), default=None, init=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer(), default=None, init=False)
    output_tokens: Mapped[int | None] = mapped_column(Integer(), default=None, init=False)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer(), default=None, init=False)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    complete_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, index=True)

    # relationships always last with init=False
    thread: Mapped["ChatThread | None"] = relationship("ChatThread", back_populates="chats", init=False)
   