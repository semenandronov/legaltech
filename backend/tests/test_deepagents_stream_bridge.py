import asyncio

from app.services.workflows.deepagents_stream_bridge import stream_parts_to_events


def test_messages_stream_is_converted_to_assistant_message_event():
    async def _collect():
        async def parts():
            yield {
                "type": "messages",
                "ns": (),
                "data": {
                    "messages": [
                        {"role": "assistant", "content": "Хронология дела: этап 1."},
                    ]
                },
            }

        return [event async for event in stream_parts_to_events(execution_id="x", parts=parts())]

    events = asyncio.run(_collect())
    assistant_events = [e for e in events if e.event_type == "assistant_message"]
    assert assistant_events, "assistant message events should be emitted from messages stream"
    assert "Хронология дела" in assistant_events[0].data.get("content", "")


def test_tuple_messages_mode_is_supported():
    async def _collect():
        async def parts():
            yield (
                "messages",
                [{"role": "assistant", "content": "Этап 2: назначение заседания."}],
            )

        return [event async for event in stream_parts_to_events(execution_id="x2", parts=parts())]

    events = asyncio.run(_collect())
    assistant_events = [e for e in events if e.event_type == "assistant_message"]
    assert assistant_events
    assert "Этап 2" in assistant_events[0].data.get("content", "")
