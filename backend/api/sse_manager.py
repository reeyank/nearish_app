import asyncio
from typing import Dict, List
from fastapi import Request

class ConnectionManager:
    def __init__(self):
        # Maps user_id -> List of active queues (one per device/tab)
        self.active_connections: Dict[str, List[asyncio.Queue]] = {}

    async def connect(self, user_id: str):
        queue = asyncio.Queue()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(queue)
        print(f"User {user_id} connected. Active devices: {len(self.active_connections[user_id])}")
        return queue

    async def disconnect(self, user_id: str, queue: asyncio.Queue):
        if user_id in self.active_connections:
            if queue in self.active_connections[user_id]:
                self.active_connections[user_id].remove(queue)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        print(f"User {user_id} disconnected.")

    async def send_event(self, user_id: str, event_type: str, data: dict):
        if user_id in self.active_connections:
            message = {"event": event_type, "data": data}
            # We send it as a JSON string mostly, but SSE format is "event: ...\ndata: ...\n\n"
            # We'll handle the formatting in the generator
            for queue in self.active_connections[user_id]:
                await queue.put(message)
            print(f"Event '{event_type}' sent to user {user_id}")
        else:
            print(f"User {user_id} is not connected. Event '{event_type}' dropped.")

manager = ConnectionManager()
