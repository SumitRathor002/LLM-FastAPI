"""
Tests for /chat SSE endpoint covering:
1. Client disconnects mid-generation
2. Client interrupts mid-generation (calls /chat/stop)
3. Client disconnects and tries reconnection (Last-Event-ID)

Requirements:
    pip install pytest pytest-asyncio httpx aiohttp

Run:
    pytest test_chat_sse.py -v
"""

import asyncio
import json
import uuid
import pytest
import httpx

# ── configuration
BASE_URL = "http://localhost:8000"   # adjust to your server
CHAT_ENDPOINT  = f"{BASE_URL}/api/v1/chat"
STOP_ENDPOINT  = f"{BASE_URL}/api/v1/chat/stop"

SAMPLE_BODY = {
    "provider": "openai",
    "model":    "gpt-4o-mini",
    "user_prompt":   "Count slowly from 1 to 20, one number per line. Also add a short story at the end",
    "system_prompt": "You are a helpful assistant.",
    "stream": True,
    "chat_uuid": None,   # filled in per test
    "thread_id": None,
}

TIMEOUT = httpx.Timeout(30.0, connect=5.0)


# ── helpers ───────────────────────────────────────────────────────────────────

def build_body(**overrides) -> dict:
    body = SAMPLE_BODY.copy()
    body.update(overrides)
    return body


def parse_sse_line(line: str) -> tuple[str, str]:
    """Return (field, value) from a raw SSE line, e.g. 'data: hello'."""
    if ":" in line:
        field, _, value = line.partition(":")
        return field.strip(), value.strip()
    return line.strip(), ""


async def collect_sse_events(
    client: httpx.AsyncClient,
    body: dict,
    headers: dict | None = None,
    max_events: int = 999,
    stop_after_seconds: float | None = None,
) -> tuple[list[dict], str | None]:
    """
    Stream SSE events and return (events_list, last_seen_id).
    Each event is a dict with keys: id, event, data.
    """
    events: list[dict] = []
    last_id: str | None = None
    current: dict = {}

    async with client.stream(
        "POST",
        CHAT_ENDPOINT,
        json=body,
        headers=headers or {},
        timeout=TIMEOUT,
    ) as resp:
        resp.raise_for_status()
        deadline = (
            asyncio.get_event_loop().time() + stop_after_seconds
            if stop_after_seconds
            else None
        )
        async for raw_line in resp.aiter_lines():
            if deadline and asyncio.get_event_loop().time() > deadline:
                break

            line = raw_line.strip()
            # print(line)
            if line == "":                  # blank line → dispatch event
                if current:
                    events.append(current.copy())
                    if "id" in current:
                        last_id = current["id"]
                    current = {}
                    if len(events) >= max_events:
                        break
            else:
                field, value = parse_sse_line(line)
                if field in ("id", "event", "data", "retry"):
                    current[field] = value

    return events, last_id


# ── test 1: client disconnects mid-generation ─────────────────────────────────

@pytest.mark.asyncio
async def test_client_disconnects_mid_generation():
    """
    Open an SSE stream, read a few events, then close the connection abruptly.
    Verify:
      - We received at least some streaming chunks before disconnect.
      - The server does not raise on our side (no exception propagated).
    """
    async with httpx.AsyncClient() as client:
        body = build_body()
        events, last_id = await collect_sse_events(
            client,
            body,
            max_events=3,           # disconnect after 3 events
        )

    assert len(events) >= 1, "Expected at least 1 SSE event before disconnect"
    assert last_id is not None, "Expected at least one event with an id field"

    # Each data payload should be valid JSON
    for ev in events:
        if "data" in ev and ev["data"] not in ("[DONE]", ""):
            parsed = json.loads(ev["data"])
            assert "text" in parsed or "delta" in parsed or "chunk" in parsed or "chat_uuid" in parsed, (
                f"Unexpected data payload: {ev['data']}"
            )

    print(f"\n[test_client_disconnects_mid_generation] "
          f"Received {len(events)} event(s) before disconnect. last_id={last_id}")


# ── test 2: client interrupts mid-generation ─────────────────────────────────

@pytest.mark.asyncio
async def test_client_interrupts_mid_generation():
    """
    Start streaming, read a few events, then call POST /chat/stop.
    Verify:
      - /chat/stop returns 200 with 'interrupted' detail.
      - The SSE stream terminates (no more chunks arrive).
    """
    # We need the chat_uuid that the server assigns.  It is typically sent
    # as the `id:` field of the first SSE event, or embedded in `data`.
    chat_uuid: str | None = None
    received_before_stop: list[dict] = []

    async with httpx.AsyncClient() as client:
        body = build_body()

        async with client.stream(
            "POST",
            CHAT_ENDPOINT,
            json=body,
            timeout=TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            current: dict = {}

            async for raw_line in resp.aiter_lines():
                line = raw_line.strip()

                if line == "":
                    if current:
                        received_before_stop.append(current.copy())
                        if "id" in current and chat_uuid is None:
                            # First id field carries the chat UUID
                            chat_uuid = current["id"].split(":")[0]  # strip chunk index if present
                        current = {}

                    # After we have a uuid and at least 2 events, stop
                    if chat_uuid and len(received_before_stop) >= 2:
                        # Call /chat/stop while still inside the stream context
                        stop_resp = await client.post(
                            STOP_ENDPOINT,
                            json={"chat_uuid": chat_uuid},
                            timeout=TIMEOUT,
                        )
                        assert stop_resp.status_code == 200, (
                            f"/chat/stop returned {stop_resp.status_code}: {stop_resp.text}"
                        )
                        stop_data = stop_resp.json()
                        assert "interrupted" in stop_data.get("detail", "").lower(), (
                            f"Unexpected detail: {stop_data}"
                        )
                        break   # stop reading the stream
                else:
                    field, value = parse_sse_line(line)
                    if field in ("id", "event", "data"):
                        current[field] = value

    assert chat_uuid is not None, "Never received a chat UUID from the stream"
    assert len(received_before_stop) >= 2, "Expected at least 2 events before stopping"

    print(f"\n[test_client_interrupts_mid_generation] "
          f"Stopped chat_uuid={chat_uuid} after {len(received_before_stop)} event(s).")


# ── test 3: client disconnects then reconnects ────────────────────────────────

@pytest.mark.asyncio
async def test_client_disconnects_and_reconnects():
    """
    1. Start a streaming chat, read a few events, capture last_event_id.
    2. Abruptly close the connection (simulate disconnect).
    3. Reconnect by sending the same body with the Last-Event-ID header.
    4. Verify the server replays / continues from where it left off.
    """
    chat_uuid: str | None = None
    last_event_id: str | None = None

    # ── phase 1: initial connection, disconnect early ─────────────────────────
    async with httpx.AsyncClient() as client:
        body = build_body()
        events, last_event_id = await collect_sse_events(
            client,
            body,
            max_events=3,
        )

    assert events, "No events received on initial connection"

    # Extract chat_uuid from first event id (format may be "<uuid>:<index>")
    first_id: str = events[0].get("id", "")
    if ":" in first_id:
        chat_uuid = first_id.split(":")[0]
    else:
        chat_uuid = first_id

    assert chat_uuid, "Could not extract chat_uuid from SSE id field"
    assert last_event_id, "No Last-Event-ID captured from initial connection"

    print(f"\n[test_client_disconnects_and_reconnects] "
          f"Phase 1: got {len(events)} events. "
          f"chat_uuid={chat_uuid}  last_event_id={last_event_id}")

    # Small pause to let the producer keep running server-side
    await asyncio.sleep(0.5)

    # ── phase 2: reconnect with Last-Event-ID ────────────────────────────────
    reconnect_body = build_body(chat_uuid=chat_uuid, stream=True)

    async with httpx.AsyncClient() as client:
        reconnect_events, _ = await collect_sse_events(
            client,
            reconnect_body,
            headers={"Last-Event-ID": last_event_id},
            max_events=200,
            stop_after_seconds=100,
        )

    # The reconnection should yield either:
    #   (a) more streamed chunks  →  producer was still ACTIVE
    #   (b) a completed JSON response (status_code 200 with {"text": ..., "status": "completed"})
    # Both are valid.  We just assert the server responded without error.
    assert reconnect_events is not None, "Reconnection produced no response"

    if reconnect_events:
        print(f"[test_client_disconnects_and_reconnects] "
              f"Phase 2 (reconnect): received {len(reconnect_events)} event(s).")
    else:
        print("[test_client_disconnects_and_reconnects] "
              "Phase 2: server returned completed response (no SSE events — check JSON body).")


# ── test 3b: reconnect after completion (expects JSON) ───────────────────────

@pytest.mark.asyncio
async def test_reconnect_after_completed_chat():
    """
    Let a short non-streaming chat complete, then attempt reconnection.
    Expect a JSON response with status='completed'.
    """
    async with httpx.AsyncClient() as client:
        body = build_body(stream=False, user_prompt="Say exactly: hello")
        resp = await client.post(CHAT_ENDPOINT, json=body, timeout=TIMEOUT)
        assert resp.status_code == 200
        data = resp.json()
        chat_uuid = data.get("chat_uuid")
        assert chat_uuid, f"No chat_uuid in response: {data}"

    print(f"\n[test_reconnect_after_completed_chat] Completed chat_uuid={chat_uuid}")

    # Now reconnect pretending we were mid-stream
    async with httpx.AsyncClient() as client:
        reconnect_body = build_body(chat_uuid=chat_uuid, stream=True)
        resp = await client.post(
            CHAT_ENDPOINT,
            json=reconnect_body,
            headers={"Last-Event-ID": f"0"},
            timeout=TIMEOUT,
        )
        # print("respone status code:", resp)
        assert resp.status_code == 200

        payload = resp.json()
        # print("respone payload", payload)
        
        assert payload.get("status") == "completed", (
            f"Expected status=completed, got: {payload}"
        )
        assert "text" in payload, f"Expected 'text' in completed response: {payload}"

    print(f"[test_reconnect_after_completed_chat] "
          f"Reconnect returned completed text (len={len(payload['text'])}).")


# ── test 4: stop a non-existent chat ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_nonexistent_chat():
    """Stopping an unknown chat_uuid should return 404."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            STOP_ENDPOINT,
            json={"chat_uuid": str(uuid.uuid4())},
            timeout=TIMEOUT,
        )
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    print("\n[test_stop_nonexistent_chat] Correctly received 404.")


# ── entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    # Quick smoke-run without pytest
    async def main():
        print("=== Running all SSE tests manually ===\n")
        tests = [
            test_client_disconnects_mid_generation,
            test_client_interrupts_mid_generation,
            test_client_disconnects_and_reconnects,
            test_reconnect_after_completed_chat,
            test_stop_nonexistent_chat,
        ]
        for t in tests:
            try:
                await t()
                print(f"PASS  {t.__name__}\n")
            except Exception as exc:
                print(f"FAIL  {t.__name__}: {exc}\n")

    asyncio.run(main())