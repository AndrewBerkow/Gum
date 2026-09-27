import asyncio

from app.devlog import DevLogBus


async def test_subscribe_then_publish_delivers_event_to_subscriber_queue():
    bus = DevLogBus()
    _, queue = bus.subscribe()

    bus.publish("turn.start", {"turn_id": "t1"})

    name, data = await asyncio.wait_for(queue.get(), timeout=1)
    assert (name, data) == ("turn.start", {"turn_id": "t1"})
