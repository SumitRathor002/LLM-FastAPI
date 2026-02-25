from datetime import datetime
from enum import StrEnum
from typing import Self
from pydantic import BaseModel, Field, field_serializer, model_validator
from uuid import UUID


class ChatStatus(StrEnum):
    INTERRUPTED = "interrupted"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class ChatRequest(BaseModel):
    model: str | None = None
    provider: str | None = None
    user_prompt: str | None = None
    system_prompt: str | None = None
    stream: bool = True
    thread_id: int | None = None
    chat_uuid: UUID | None = None

    @model_validator(mode="after")
    def validate_required_fields(self) -> Self:
        if self.chat_uuid is None:
            # New chat — these fields are mandatory
            missing = [
                field for field, val in {
                    "user_prompt": self.user_prompt,
                    "provider": self.provider,
                    "model": self.model,
                }.items() if not val
            ]
            if missing:
                raise ValueError(
                    f"Fields required for new chat: {', '.join(missing)}"
                )
        return self


class StopRequest(BaseModel):
    chat_uuid: str


class ChatResponse(BaseModel):
    chat_uuid: UUID = Field(alias="uuid")
    user_prompt: str
    response: str = Field(alias="llm_response")  
    status: str
    model: str
    provider: str
    thread_id: int
    created_at: datetime

    @field_serializer("chat_uuid")
    def serialize_uuid(self, value: UUID) -> str:
        return str(value)
    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }