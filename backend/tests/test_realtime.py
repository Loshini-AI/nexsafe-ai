import asyncio
import json
import unittest

from app import realtime


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.messages: list[str] = []
        self.received = asyncio.Event()

    async def accept(self):
        self.accepted = True

    async def send_text(self, message: str):
        self.messages.append(message)
        self.received.set()


class RealtimeFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_event_bus_delivers_user_scoped_messages_without_redis(self):
        previous_redis_state = realtime._redis_available
        realtime._redis_available = False
        websocket = FakeWebSocket()
        subscription = asyncio.create_task(realtime.subscribe(websocket, "local-user"))
        try:
            await asyncio.sleep(0)
            await realtime.publish_event("local-user", {"type": "camera.status", "status": "connected"})
            await asyncio.wait_for(websocket.received.wait(), timeout=1)

            self.assertTrue(websocket.accepted)
            self.assertEqual(
                json.loads(websocket.messages[0]),
                {"type": "camera.status", "status": "connected"},
            )
        finally:
            subscription.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await subscription
            realtime._redis_available = previous_redis_state


if __name__ == "__main__":
    unittest.main()
