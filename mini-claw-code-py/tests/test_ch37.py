import asyncio

import pytest

from mini_claw_code_py import EventEnvelope, MessageBus, MessageEnvelope, create_envelope_id, create_trace_id


def test_ch37_message_envelope_defaults_ids_and_timestamps() -> None:
    envelope = MessageEnvelope(
        source="cli",
        target_agent="superagent",
        thread_key="cli:local",
        kind="user_message",
        content="Build feature A",
    )

    assert envelope.message_id.startswith("msg_")
    assert envelope.trace_id.startswith("trace_")
    assert envelope.created_at.endswith("Z")
    assert envelope.parent_run_id is None
    assert envelope.metadata == {}


def test_ch37_event_envelope_defaults_ids_and_timestamps() -> None:
    envelope = EventEnvelope(kind="run_started", payload={"run_id": "run_1"})

    assert envelope.event_id.startswith("evt_")
    assert envelope.trace_id.startswith("trace_")
    assert envelope.created_at.endswith("Z")
    assert envelope.payload == {"run_id": "run_1"}


def test_ch37_create_helpers_use_expected_prefixes() -> None:
    assert create_envelope_id().startswith("msg_")
    assert create_envelope_id("evt").startswith("evt_")
    assert create_trace_id().startswith("trace_")


def test_ch37_message_envelope_rejects_empty_routing_fields() -> None:
    with pytest.raises(ValueError):
        MessageEnvelope(
            source="",
            target_agent="superagent",
            thread_key="cli:local",
            kind="user_message",
            content="hello",
        )
    with pytest.raises(ValueError):
        MessageEnvelope(
            source="cli",
            target_agent="",
            thread_key="cli:local",
            kind="user_message",
            content="hello",
        )
    with pytest.raises(ValueError):
        MessageEnvelope(
            source="cli",
            target_agent="superagent",
            thread_key="",
            kind="user_message",
            content="hello",
        )


def test_ch37_rejects_unknown_kinds() -> None:
    with pytest.raises(ValueError):
        MessageEnvelope(
            source="cli",
            target_agent="superagent",
            thread_key="cli:local",
            kind="bad",  # type: ignore[arg-type]
            content="hello",
        )
    with pytest.raises(ValueError):
        EventEnvelope(kind="bad", payload={})  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_ch37_message_bus_preserves_inbound_fifo_order() -> None:
    bus = MessageBus()
    first = MessageEnvelope(
        source="cli",
        target_agent="superagent",
        thread_key="cli:local",
        kind="user_message",
        content="first",
    )
    second = MessageEnvelope(
        source="cli",
        target_agent="superagent",
        thread_key="cli:local",
        kind="user_message",
        content="second",
    )

    await bus.publish_inbound(first)
    await bus.publish_inbound(second)

    assert bus.inbound_size() == 2
    assert (await bus.consume_inbound()).content == "first"
    assert (await bus.consume_inbound()).content == "second"
    assert bus.inbound_size() == 0


@pytest.mark.asyncio
async def test_ch37_message_bus_keeps_inbound_outbound_and_events_separate() -> None:
    bus = MessageBus()
    inbound = MessageEnvelope(
        source="cli",
        target_agent="superagent",
        thread_key="cli:local",
        kind="user_message",
        content="inbound",
    )
    outbound = MessageEnvelope(
        source="system",
        target_agent="superagent",
        thread_key="cli:local",
        kind="system_message",
        content="outbound",
    )
    event = EventEnvelope(kind="operator_event", payload={"message": "hello"})

    await bus.publish_inbound(inbound)
    await bus.publish_outbound(outbound)
    await bus.publish_event(event)

    assert bus.inbound_size() == 1
    assert bus.outbound_size() == 1
    assert bus.event_size() == 1

    assert (await bus.consume_inbound()).content == "inbound"
    assert (await bus.consume_outbound()).content == "outbound"
    assert (await bus.consume_event()).payload["message"] == "hello"


@pytest.mark.asyncio
async def test_ch37_trace_id_can_be_propagated_across_related_envelopes() -> None:
    bus = MessageBus()
    trace_id = create_trace_id()
    request = MessageEnvelope(
        source="cli",
        target_agent="superagent",
        thread_key="cli:local",
        kind="user_message",
        content="Build feature A",
        trace_id=trace_id,
    )
    result_event = EventEnvelope(
        kind="run_finished",
        payload={"status": "ok"},
        trace_id=trace_id,
    )

    await bus.publish_inbound(request)
    await bus.publish_event(result_event)

    assert (await bus.consume_inbound()).trace_id == trace_id
    assert (await bus.consume_event()).trace_id == trace_id
