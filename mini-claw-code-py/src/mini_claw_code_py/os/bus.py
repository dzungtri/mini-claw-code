from __future__ import annotations

import asyncio

from .envelopes import EventEnvelope, MessageEnvelope


class MessageBus:
    def __init__(self) -> None:
        self._inbound: asyncio.Queue[MessageEnvelope] = asyncio.Queue()
        self._outbound: asyncio.Queue[MessageEnvelope] = asyncio.Queue()
        self._events: asyncio.Queue[EventEnvelope] = asyncio.Queue()

    async def publish_inbound(self, envelope: MessageEnvelope) -> None:
        await self._inbound.put(envelope)

    async def consume_inbound(self) -> MessageEnvelope:
        return await self._inbound.get()

    async def publish_outbound(self, envelope: MessageEnvelope) -> None:
        await self._outbound.put(envelope)

    async def consume_outbound(self) -> MessageEnvelope:
        return await self._outbound.get()

    async def publish_event(self, envelope: EventEnvelope) -> None:
        await self._events.put(envelope)

    async def consume_event(self) -> EventEnvelope:
        return await self._events.get()

    def inbound_size(self) -> int:
        return self._inbound.qsize()

    def outbound_size(self) -> int:
        return self._outbound.qsize()

    def event_size(self) -> int:
        return self._events.qsize()
