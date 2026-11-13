import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger("nexsafe.realtime")
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
_redis_available: bool | None = None
_local_subscribers: dict[str, set[asyncio.Queue[str]]] = defaultdict(set)
_local_subscribers_lock = asyncio.Lock()
_local_queue_limit = 128


async def redis_available() -> bool:
    global _redis_available
    try:
        await redis_client.ping()
        _redis_available = True
        return True
    except RedisError as exc:
        _redis_available = False
        logger.warning(
            "Redis is unavailable; using the process-local event bus (%s)",
            type(exc).__name__,
        )
        return False


async def _publish_local(channel: str, message: str) -> None:
    async with _local_subscribers_lock:
        subscribers = tuple(_local_subscribers.get(channel, ()))
    for queue in subscribers:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            queue.put_nowait(message)
            logger.warning("Dropped the oldest queued real-time message for a slow client")


async def _subscribe_local(websocket: WebSocket, channel: str) -> None:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_local_queue_limit)
    async with _local_subscribers_lock:
        _local_subscribers[channel].add(queue)
    try:
        while True:
            await websocket.send_text(await queue.get())
    finally:
        async with _local_subscribers_lock:
            subscribers = _local_subscribers.get(channel)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    _local_subscribers.pop(channel, None)


async def publish_event(user_id: str, payload: dict) -> None:
    global _redis_available
    channel = f"nexsafe:events:{user_id}"
    message = json.dumps(payload, default=str)
    if _redis_available is not False:
        try:
            await redis_client.publish(channel, message)
            _redis_available = True
            await _publish_local(channel, message)
            return
        except RedisError as exc:
            _redis_available = False
            logger.warning(
                "Redis publish failed; using the process-local event bus (%s)",
                type(exc).__name__,
            )
    await _publish_local(channel, message)


async def subscribe(websocket: WebSocket, user_id: str) -> None:
    global _redis_available
    await websocket.accept()
    channel = f"nexsafe:events:{user_id}"
    if _redis_available is False:
        await _subscribe_local(websocket, channel)
        return

    pubsub = None
    try:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        _redis_available = True
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except RedisError as exc:
        _redis_available = False
        logger.warning(
            "Redis subscription failed; using the process-local event bus (%s)",
            type(exc).__name__,
        )
        await _subscribe_local(websocket, channel)
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except RedisError as exc:
                logger.warning("Redis subscription cleanup failed (%s)", type(exc).__name__)
