import asyncio

from app.devlog import DevLogBus


async def test_subscribe_then_publish_delivers_event_to_subscriber_queue():
    bus = DevLogBus()
    _, queue = bus.subscribe()

    bus.publish("turn.start", {"turn_id": "t1"})

    name, data = await asyncio.wait_for(queue.get(), timeout=1)
    assert (name, data) == ("turn.start", {"turn_id": "t1"})


async def test_stream_replays_history_before_live_events():
    bus = DevLogBus()
    bus.publish("turn.start", {"n": 1})
    bus.publish("turn.end", {"n": 2})

    seen = []
    gen = bus.stream()
    seen.append(await asyncio.wait_for(gen.__anext__(), timeout=1))
    seen.append(await asyncio.wait_for(gen.__anext__(), timeout=1))

    bus.publish("turn.start", {"n": 3})
    seen.append(await asyncio.wait_for(gen.__anext__(), timeout=1))
    await gen.aclose()

    assert seen == [("turn.start", {"n": 1}), ("turn.end", {"n": 2}), ("turn.start", {"n": 3})]


async def test_history_ring_buffer_evicts_oldest_past_configured_size():
    bus = DevLogBus(history_size=3)
    for i in range(5):
        bus.publish("e", {"n": i})

    history, _ = bus.subscribe()
    assert [d["n"] for _, d in history] == [2, 3, 4]


async def test_publish_drops_oldest_item_when_subscriber_queue_is_full():
    bus = DevLogBus(queue_size=2)
    _, queue = bus.subscribe()

    bus.publish("e", {"n": 1})
    bus.publish("e", {"n": 2})
    bus.publish("e", {"n": 3})  # never blocks even though nothing has read the queue yet

    assert queue.qsize() == 2
    first = await asyncio.wait_for(queue.get(), timeout=1)
    second = await asyncio.wait_for(queue.get(), timeout=1)
    assert [first[1]["n"], second[1]["n"]] == [2, 3]


async def test_stream_without_replay_skips_history_and_yields_only_new_events():
    bus = DevLogBus()
    bus.publish("turn.start", {"n": 1})

    gen = bus.stream(replay=False)
    nxt = asyncio.ensure_future(gen.__anext__())
    await asyncio.sleep(0)
    bus.publish("turn.start", {"n": 2})
    got = await asyncio.wait_for(nxt, timeout=1)
    await gen.aclose()

    assert got == ("turn.start", {"n": 2})
