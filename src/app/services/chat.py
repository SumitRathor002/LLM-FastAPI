import asyncio
from collections.abc import Coroutine
from datetime import datetime, UTC, timedelta
import json
import re
from typing import Any, AsyncGenerator, List, Literal
from uuid import UUID
import redis.asyncio as aioredis
import structlog
from ..core.llm.utils import completion_call, extract_chunk_text, extract_usage
from ..core.llm.schemas import UserMessage, AssistantMessage, Message
from ..models import Chat, ChatThread
from sqlalchemy.ext.asyncio import AsyncSession
from ..schemas.chat import ChatRequest, ChatStatus
from ..core.utils.cache import buffer_key, get_status, set_status, status_key
from litellm.types.utils import ModelResponse
from ..core.config import settings
from sqlalchemy import update, select, asc, desc
from ..core.db.database import local_session

logger = structlog.get_logger(__name__)


async def save_chat(
        db: AsyncSession,
        status: ChatStatus, 
        chat_request: ChatRequest, 
        llm_response: ModelResponse | None | str = None,
    ):  
    
    try:
        async with db.begin():
            thread_id = chat_request.thread_id

            if not chat_request.thread_id:
                thread = ChatThread(
                    thread_title=chat_request.user_prompt[:100],
                )
                db.add(thread)
                await db.flush()  # assigns thread.id without committing
                thread_id = thread.id

            if not llm_response:
                text = ""

            usage = {}
            if isinstance(llm_response, ModelResponse):
                text  = llm_response.choices[0].message.content
                usage = extract_usage(llm_response)

            elif isinstance(llm_response, str):
                text = llm_response

            chat = Chat(
                user_prompt=chat_request.user_prompt,
                final_prompt=chat_request.user_prompt,
                llm_response=text,
                model=chat_request.model,
                provider=chat_request.provider,
                status=status,
                role="assistant",
                thread_id=thread_id,
                complete_response=llm_response.model_dump() if hasattr(llm_response, "model_dump") else None,
            )
            chat.total_tokens = usage.get("total_tokens")
            chat.input_tokens = usage.get("input_tokens")
            chat.output_tokens = usage.get("output_tokens")
            chat.reasoning_tokens = usage.get("reasoning_tokens")

            db.add(chat)
            await db.flush()  # validate constraints before commit

        # refresh outside the transaction (connection is released after commit)
        await db.refresh(chat)
        return chat

    except Exception as e:
        logger.exception("save_chat failed", error=str(e))
        raise


async def get_chats_for_thread(
        thread_id: int,
        db: AsyncSession,
        order: Literal["asc", "desc"] = "asc",
    ) -> List[Chat]:
    try:
        order_func = desc if order == "desc" else asc
        rows = (
            await db.execute(
                select(Chat)
                .where(
                    Chat.thread_id == thread_id,
                    Chat.is_deleted == False
                )
                .order_by(order_func(Chat.created_at))
            )
        ).scalars().all()

        return rows
    except Exception:
        logger.exception("Getting chats for a thread failed.")


def format_previous_messages(chats: list[Chat]) -> list[Message]:
    messages = []
    for chat in chats: 
        messages.append(UserMessage(content=chat.user_prompt))
        if chat.llm_response:
            messages.append(AssistantMessage(content=chat.llm_response))
    return messages


# Producer 
async def producer(
    queue: asyncio.Queue,
    db: AsyncSession,
    redis: aioredis.Redis,
    chat: Chat,   
    previous_messages: list[Message],                 
    chat_request: ChatRequest,
) -> None:
    redis_buf: list[str] = []
    db_buf: list[str] = []
    all_chunks: list[str] = [] 
    final_usage: dict | None = None
    status = ChatStatus.COMPLETED
    chat_uuid_str: str = str(chat.uuid)
    # helpers
    async def flush_to_redis(items: list[str]) -> None:
        """
        Batch RPUSH items into Redis list + set TTL in one pipeline.
        Pipeline executes all commands in a single round-trip.
        You cannot GET and SET in the same pipeline because GET results
        aren't available until execute() returns — but we don't need to
        GET here, so pipeline is fine.
        """
        if not items:
            return
        try:
            pipe = redis.pipeline()
            for item in items:
                pipe.rpush(buffer_key(chat_uuid_str), item)
            # Reset TTL on every flush so active streams never expire mid-generation
            pipe.expire(buffer_key(chat_uuid_str), settings.REDIS_TTL_S)
            await pipe.execute()
            logger.debug("flushed to tokens to redis")
        except Exception:
            logger.warning("Redis flush failed — continuing without Redis", exc_info=True)

    async def flush_to_db(items: list[str], final: bool = False) -> None:
        """
        Partial or final DB write.
        On final=True: clean the response before storing.
        On final=False: store raw (placeholders included) for partial recovery.
        """
        if not items:
            return
        content = "".join(items)
        if final:
            content = clean_response(content)

        values: dict = {
            "llm_response": content,
            "updated_at": datetime.now(UTC),
        }
        if final and final_usage:
            values.update({
                "input_tokens": final_usage.get("input_tokens"),
                "output_tokens": final_usage.get("output_tokens"),
                "reasoning_tokens": final_usage.get("reasoning_tokens"),
                "total_tokens": final_usage.get("total_tokens"),
                "status": status.value,
            })

        await db.execute(
            update(Chat)
            .where(Chat.uuid == chat.uuid)
            .values(**values)
        )
        await db.commit()
        logger.debug("flushed to tokens to db")
    
    async def check_cancellation() -> bool:
        """
        Check Redis for external interrupt signal.
        Falls back to DB if Redis is unavailable.
        """
        try:
            chat_status = await get_status(redis, chat_uuid_str)
            return chat_status == ChatStatus.INTERRUPTED
        except Exception:
            # fall back to DB
            result = await db.execute(
                select(Chat.status).where(Chat.uuid == chat.uuid)
            )
            row = result.scalar_one_or_none()
            return row == ChatStatus.INTERRUPTED.value

    
    try:

        stream = await completion_call(
            model=chat_request.model,
            user_prompt=chat_request.user_prompt,
            system_prompt=chat_request.system_prompt,
            previous_messages=previous_messages,
            stream=True,
        )

        if stream is None:
            status = ChatStatus.FAILED
            # rest can be done in finally block
            return

        async with asyncio.timeout(settings.TOTAL_RESPONSE_TIMEOUT_S):
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        anext(stream),
                        timeout=settings.ALIVE_INTERVAL_S,
                    )
                    text = extract_chunk_text(chunk)

                    # Last chunk carries usage when include_usage=True
                    if getattr(chunk, "usage", None):
                        final_usage = extract_usage(chunk)

                    if text is None:
                        continue

                except StopAsyncIteration:
                    break   # stream exhausted normally

                except asyncio.TimeoutError:
                    # LLM went silent — emit heartbeat so consumer knows we're alive
                    logger.debug(
                        "Stream stalled for %ss, emitting heartbeat",
                        settings.ALIVE_INTERVAL_S,
                    )
                    text = settings.HEARTBEAT_PLACEHOLDER

                # accumulate
                redis_buf.append(text)
                db_buf.append(text)
                all_chunks.append(text)
                await queue.put(text) # consumer reads from here for SSE

                # flush redis every N chunks 
                if len(redis_buf) >= settings.REDIS_FLUSH_EVERY_N:
                    asyncio.create_task(flush_to_redis(redis_buf.copy()))
                    redis_buf.clear()

                # partial DB write every M chunks
                if len(db_buf) >= settings.DB_FLUSH_EVERY_M:
                    asyncio.create_task(flush_to_db(db_buf.copy(), final=False))  
                    # Do NOT clear all_chunks — we need the full history for final save
                    db_buf.clear()

                # external interrupt
                if await check_cancellation():
                    logger.debug("Chat Interrupted")
                    status = ChatStatus.INTERRUPTED
                    all_chunks.append(settings.INTERRUPTED_PLACEHOLDER)
                    await queue.put(settings.INTERRUPTED_PLACEHOLDER)
                    break

    except asyncio.TimeoutError:
        # Outer total timeout fired
        logger.warning("Total response timeout hit for chat %s", chat_uuid_str)
        status = ChatStatus.FAILED
        all_chunks.append(settings.FAILED_PLACEHOLDER)
        await queue.put(settings.FAILED_PLACEHOLDER)

    except Exception:
        logger.exception("Producer error", extra={"chat_uuid": chat_uuid_str})
        status = ChatStatus.FAILED
        all_chunks.append(settings.FAILED_PLACEHOLDER)
        await queue.put(settings.FAILED_PLACEHOLDER)

    finally:
        # always runs
        terminal = settings.DONE_PLACEHOLDER
        if status == ChatStatus.FAILED:
            terminal = settings.FAILED_PLACEHOLDER

        elif status == ChatStatus.INTERRUPTED:
            terminal = settings.INTERRUPTED_PLACEHOLDER
        
        redis_buf.append(terminal)
        db_buf.append(terminal)
        all_chunks.append(terminal)
        await queue.put(terminal)

        # Flush whatever remains in redis buffer + terminal marker
        await flush_to_redis(redis_buf)
        redis_buf.clear()

        # Final DB write — this is where we clean the response
        # all_chunks has the complete raw history including placeholders
        await flush_to_db(all_chunks, final=True)

        # Update status in Redis so consumers know the stream is done
        await set_status(redis, chat_uuid_str, status)


# SSE generator (consumer) 
async def stream_generator(
        queue: asyncio.Queue,
        chat: Chat, 
        producer_task:  Coroutine[Any, Any, Any]                 
    ) -> AsyncGenerator[str, None]:

    chat_uuid_str: str = str(chat.uuid)
    # Send chat UUID as the SSE event id immediately so the client can
    # use it as Last-Event-ID for reconnection. 
    yield f"id: {chat_uuid_str}\nevent: init\ndata: {json.dumps({'chat_uuid': chat_uuid_str, 'thread_id': chat.thread_id})}\nretry: {settings.SSE_RECONNECTION_DELAY_MS}\n\n"
    chunk_idx = 0
    try:
        while True:
            chunk = await asyncio.wait_for(queue.get(), timeout=settings.ALIVE_INTERVAL_S)

            if chunk == settings.HEARTBEAT_PLACEHOLDER:
                # ':' colon which marks this event as comment and we do not add this to response
                yield f": PING, WE ARE STILL GENERATING RESPONSE"
                
            elif chunk == settings.DONE_PLACEHOLDER:
                yield f"id: {chunk_idx}\nevent: done\ndata: [DONE]\n\n"
                break
            elif chunk == settings.FAILED_PLACEHOLDER:
                yield f"id: {chunk_idx}\nevent: failed\ndata: [FAILED]\n\n"
                break
            elif chunk == settings.INTERRUPTED_PLACEHOLDER:
                yield f"id: {chunk_idx}\nevent: done\ndata: [INTERRUPT]\n\n"
                break
            
            yield f"id: {chunk_idx}\nevent: chunk\ndata: {json.dumps({'text': chunk})}\n\n"
            chunk_idx += 1

    except asyncio.CancelledError:
        # Client disconnected — mark interrupted so producer stops cleanly
        logger.info("Client disconnected", chat_uuid=chat_uuid_str)

    finally:
        try:
            await asyncio.shield(producer_task)
        except asyncio.CancelledError:
            pass

    

async def reconnect_stream(
    redis: aioredis.Redis,
    db: AsyncSession,
    chat: Chat,
    last_event_id: int,
) -> AsyncGenerator[str, None]:
    """
    Replay the Redis buffer from last_event_id onward, then poll for new
    chunks until the stream completes or the remaining generation window
    expires.

    Time-bounding logic:
        deadline = chat.created_at + TOTAL_RESPONSE_TIMEOUT_S
        remaining = deadline - now()
    If remaining <= 0 the window has already passed — emit failed and exit.
    """
    chat_uuid = str(chat.uuid)
    thread_id = chat.thread_id
    yield (
        f"id: {chat_uuid}\nevent: init\n"
        f"data: {json.dumps({'chat_uuid': chat_uuid, 'thread_id': thread_id, 'reconnected': True})}\n\n"
    )
    chat = await db.execute(
            select(Chat.status, Chat.created_at).where(Chat.uuid == UUID(chat_uuid))
        )
    row = chat.one_or_none()
    if row is None:
        yield f"id: {chat_uuid}\nevent: failed\ndata: [FAILED] No such chat found\n\n"
        return

    if row.status != ChatStatus.ACTIVE:
        yield f"id: {chat_uuid}\nevent: {row.status}\ndata: [{row.status}]\n\n"
        return

    # Time gate
    deadline: datetime = row.created_at + timedelta(seconds=settings.TOTAL_RESPONSE_TIMEOUT_S)
    remaining: float = (deadline - datetime.now(UTC)).total_seconds()

    if remaining <= 0:
        yield f"id: {chat_uuid}\nevent: failed\ndata: [FAILED]\n\n"
        return

    sent_so_far: int = last_event_id if last_event_id != 0 else -1 # index into the Redis list
    redis_poll_interval: int | float = settings.RECONNECT_POLL_INTERVAL_REDIS_S
    db_poll_interval: int | float =  settings.RECONNECT_POLL_INTERVAL_DB_S   # hit DB ~6x less often
    deadline_monotonic: float = asyncio.get_event_loop().time() + remaining

    # helpers
    async def _fetch_redis() -> tuple[ChatStatus | None, list[str]]:
        """Single round-trip: get status + buffer slice in one pipeline."""
        try:
            pipe = redis.pipeline()
            pipe.get(status_key(chat_uuid))
            pipe.lrange(buffer_key(chat_uuid), sent_so_far, -1)
            status_raw, chunks = await pipe.execute()
            status = ChatStatus(status_raw.decode()) if status_raw else None
            decoded = [c.decode() if isinstance(c, bytes) else c for c in chunks]
            logger.debug(f"Polled redis: {decoded}", )
            return status, decoded
        except Exception as e:
            logger.exception(f"fetch redis failed: {e}")
            raise 

    async def _fetch_db() -> tuple[ChatStatus | None, str]:
        """Fallback: DB polling"""
        result = await db.execute(
            select(Chat.status, Chat.llm_response).where(Chat.uuid == UUID(chat_uuid))
        )
        row = result.one_or_none()
        if row is None:
            return None, ""
        status = ChatStatus(row.status) if row.status else None
        logger.debug(f"Polled db: {row.llm_response}")
        return status, row.llm_response or ""

    use_redis: bool = True
    db_content_sent: int = 0  # char offset for DB fallback

    while asyncio.get_event_loop().time() < deadline_monotonic:
        status: ChatStatus | None = None
        terminal: bool = False

        if use_redis:
            try:
                status, new_chunks = await _fetch_redis()

                # Filter out internal placeholders before sending to client
                for chunk in new_chunks:
                    sent_so_far += 1
                    if chunk in (
                        settings.HEARTBEAT_PLACEHOLDER,
                        settings.DONE_PLACEHOLDER,
                        settings.FAILED_PLACEHOLDER,
                        settings.INTERRUPTED_PLACEHOLDER,
                    ):
                        continue
                    yield (
                        f"id: {sent_so_far}\nevent: chunk\n"
                        f"data: {json.dumps({'text': chunk})}\n\n"
                    )

            except Exception:
                logger.exception("Redis unavailable in reconnect_stream. switching to DB poll")
                use_redis = False
                # fall through to DB branch immediately this iteration

        if not use_redis:
            try:
                status, full_content = await _fetch_db()
                new_content = full_content[db_content_sent:]
                if new_content:
                    # Stream the new slice as a single chunk to the client
                    yield (
                        f"id: {sent_so_far}\nevent: chunk\n"
                        f"data: {json.dumps({'text': new_content})}\n\n"
                    )
                    db_content_sent += len(new_content)
            except Exception:
                logger.warning("DB poll failed in reconnect_stream", exc_info=True)


        if status in (ChatStatus.COMPLETED, ChatStatus.INTERRUPTED, ChatStatus.FAILED):
            terminal = True

        if terminal:
            if status == ChatStatus.COMPLETED:
                yield f"id: {sent_so_far}\nevent: done\ndata: [DONE]\n\n"
            elif status == ChatStatus.INTERRUPTED:
                yield f"id: {sent_so_far}\nevent: done\ndata: [INTERRUPT]\n\n"
            else:
                yield f"id: {sent_so_far}\nevent: failed\ndata: [FAILED]\n\n"
            return

        interval = redis_poll_interval if use_redis else db_poll_interval
        time_left = deadline_monotonic - asyncio.get_event_loop().time()
        await asyncio.sleep(min(interval, max(time_left, 0)))

    logger.warning("Reconnect stream deadline exceeded for chat %s", chat_uuid)
    yield f"id: {sent_so_far}\nevent: failed\ndata: [FAILED]\n\n"




def clean_response(raw: str) -> str:
    """
    Strip all internal placeholders from the accumulated response.
    Only call this before final DB storage — never during streaming.
    """
    placeholders = [
        re.escape(settings.HEARTBEAT_PLACEHOLDER),
        re.escape(settings.INTERRUPTED_PLACEHOLDER),
        re.escape(settings.FAILED_PLACEHOLDER),
        re.escape(settings.DONE_PLACEHOLDER),
    ]
    pattern = "|".join(placeholders)
    return re.sub(pattern, "", raw).strip()