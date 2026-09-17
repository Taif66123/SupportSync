"""Live per-ticket chat connections: an in-process registry.

Buffers nothing to disk — on reconnect clients fetch history via REST. For the
single-process M2 deployment this registry is complete; M3's Redis fan-out replaces
the cross-process gap it leaves.
"""

from dataclasses import dataclass, field

from fastapi import WebSocket

from app.modules.chat.schemas import MessageNew, ReadReceipt, TypingUpdate



@dataclass
class TicketRoom:
    connections: dict[int, WebSocket] = field(default_factory=dict)  # user_id → socket

    def add(self, user_id: int, ws: WebSocket) -> WebSocket | None:
        # One live socket per user per room; a reconnecting client replaces its own
        # stale socket but never disturbs other participants.
        old = self.connections.get(user_id)
        self.connections[user_id] = ws
        return old

    def remove(self, user_id: int, ws: WebSocket) -> bool:
        if self.connections.get(user_id) is ws:
            del self.connections[user_id]
            return True
        return False


class ConnectionRegistry:
    def __init__(self) -> None:
        self._rooms: dict[int, TicketRoom] = {}

    def room(self, ticket_id: int) -> TicketRoom:
        room = self._rooms.get(ticket_id)
        if room is None:
            room = TicketRoom()
            self._rooms[ticket_id] = room
        return room

    def drop_room_if_empty(self, ticket_id: int) -> None:
        room = self._rooms.get(ticket_id)
        if room is not None and not room.connections:
            del self._rooms[ticket_id]

    async def broadcast(
        self,
        ticket_id: int,
        frame: MessageNew | TypingUpdate | ReadReceipt,
        *,
        exclude: int | None = None,
    ) -> None:
        """Send a frame to everyone currently in the room (minus `exclude`)."""
        room = self.room(ticket_id)
        for user_id, ws in list(room.connections.items()):
            if user_id != exclude:
                await ws.send_json(frame.model_dump(mode="json"))


registry = ConnectionRegistry()
