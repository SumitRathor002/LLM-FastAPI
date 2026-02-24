from uuid import UUID

from fastapi import APIRouter, Depends
from typing import Annotated
from sqlalchemy.ext.asyncio import AsyncSession
import structlog
from ...core.db.database import async_get_db
from ...core.utils.cache import async_get_redis, get_status, set_status
import asyncio
from datetime import datetime, UTC
import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from ...schemas.chat import (
    ChatRequest,
    StopRequest,
    ChatStatus
)
from ...models.chat import (
    Chat
)
from ...services.chat import producer, reconnect_stream, save_chat, stream_generator 
from ...core.llm.utils import completion_call, extract_usage
logger = structlog.get_logger(__name__)


router = APIRouter(tags=["chat"])

@router.post("/chat", status_code=200)
async def start_chat(
    body: ChatRequest,
    redis: Annotated[aioredis.Redis, Depends(async_get_redis)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
    last_event_id: int | None = Header(None, alias="Last-Event-ID"),
):
    model_id = f"{body.provider}/{body.model}"

    # Reconnection attempt
    # The client sends the chat UUID it received in the SSE `id:` field.
    if body.chat_uuid:
        if not last_event_id:
            last_event_id = 0
        # either has continue from begining or chat index, that last event id
        chat_uuid = str(body.chat_uuid)
        row = (await db.execute(
            select(Chat).where(Chat.uuid == UUID(chat_uuid))
        )).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="No such chat found") 
        
        logger.debug(f"reconnection chat status: {row.status}")
        if row.status == ChatStatus.ACTIVE:
            # Producer still running — replay buffer then poll for new data.
            return StreamingResponse(
                reconnect_stream(redis, db, chat_uuid, last_event_id),
                media_type="text/event-stream",
            )

        return JSONResponse({"text": row.llm_response, "status": row.status})
                        
    if not body.stream:
        response = await completion_call(
            model=model_id,
            user_prompt=body.user_prompt,
            system_prompt=body.system_prompt,
        )
        if response is None:
            raise HTTPException(status_code=502, detail="LLM call failed.")

        text  = response.choices[0].message.content
        usage = extract_usage(response)
        chat = await save_chat(
            db=db,
            status=ChatStatus.COMPLETED,
            llm_response=response, 
            chat_request=body
        )
        return JSONResponse({
            "chat_uuid": str(chat.uuid),
            "text": text,
            "usage": usage,
            "thread_id": chat.thread_id,
        })
    
    
    chat = await save_chat(
            db=db,
            status=ChatStatus.ACTIVE,
            llm_response="", 
            chat_request=body
        )
    db.add(chat)
    await db.commit()
    await db.refresh(chat)

    chat_uuid_str = str(chat.uuid)
    await set_status(redis, chat_uuid_str, ChatStatus.ACTIVE)

    queue = asyncio.Queue()
    producer_task = asyncio.create_task(producer(
        queue=queue,
        db = db,
        redis=redis,
        chat=chat,
        chat_request=body
    ))
    stream_gen = stream_generator(
        queue=queue,
        chat=chat,
        producer_task=producer_task # runs the producer task in asycio.shield
    )

    return StreamingResponse(stream_gen, media_type="text/event-stream")


@router.post("/chat/stop", status_code=200)
async def stop_chat(
    body:  StopRequest,
    redis: Annotated[aioredis.Redis, Depends(async_get_redis)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
):
    chat_uuid_str = str(body.chat_uuid)
    status = await get_status(redis, chat_uuid_str)

    if status is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")

    if status != ChatStatus.ACTIVE:
        return {"detail": f"Chat is already '{status.value}'.", "chat_uuid": chat_uuid_str}

    # Signal the producer to stop on its next chunk
    await set_status(redis, chat_uuid_str, ChatStatus.INTERRUPTED)

    # Mirror the status change in the DB row
    row = (await db.execute(select(Chat).where(Chat.uuid == UUID(chat_uuid_str)))).scalar_one_or_none()
    if row:
        row.updated_at = datetime.now(UTC)
        row.status = ChatStatus.INTERRUPTED
        await db.commit()

    return {"detail": "Chat interrupted.", "chat_uuid": chat_uuid_str}