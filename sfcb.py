# sfcb - A maubot plugin that handles the switch friend codesharing widget on #switch:half-shot.uk
# Copyright (C) 2018 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from typing import Dict
from pkg_resources import resource_string
import asyncio
import json

from aiohttp import web
from jinja2 import Template

from mautrix.types import RoomID, UserID, StateEvent, EventType
from mautrix.errors import MNotFound

from maubot import Plugin, MessageEvent
from maubot.handlers import command, event

STATE_SWITCH_FRIEND_CODES = EventType("xyz.maubot.switch.friendcodes", EventType.Class.STATE)


class SwitchFriendCodeBot(Plugin):
    cache: Dict[RoomID, Dict[UserID, str]]
    cache_lock: Dict[RoomID, asyncio.Lock]

    async def start(self) -> None:
        await super().start()
        self.cache = {}
        self.cache_lock = {}
        self.webapp.add_get("/codes", self.get_widget)
        self.webapp.add_get("/codes.json", self.get_json)
        self.widget_tpl = Template(resource_string("sfcb", "widget.html.j2").decode("utf-8"))

    async def stop(self) -> None:
        await super().stop()
        self.webapp.clear()

    def _lock(self, room_id: RoomID) -> asyncio.Lock:
        try:
            return self.cache_lock[room_id]
        except KeyError:
            lock = asyncio.Lock()
            self.cache_lock[room_id] = lock
            return lock

    async def get_codes(self, room_id: RoomID) -> Dict[UserID, str]:
        async with self._lock(room_id):
            try:
                return self.cache[room_id]
            except KeyError:
                pass

            try:
                state = await self.client.get_state_event(room_id, STATE_SWITCH_FRIEND_CODES)
                self.cache[room_id] = state.serialize()
            except MNotFound:
                self.cache[room_id] = {}
            return self.cache[room_id]

    @command.new("code", help="Share your Switch friend code")
    @command.argument("code", required=True)
    async def set_code(self, evt: MessageEvent, code: str) -> None:
        if code.startswith("SW-"):
            code = code[len("SW-"):]
        cache = await self.get_codes(evt.room_id)
        cache[evt.sender] = code
        await self.client.send_state_event(room_id=evt.room_id,
                                           event_type=STATE_SWITCH_FRIEND_CODES,
                                           content=cache)
        await evt.mark_read()

    @event.on(STATE_SWITCH_FRIEND_CODES)
    async def handle_code(self, evt: StateEvent) -> None:
        self.cache[evt.room_id] = evt.content.serialize()

    async def get_widget(self, request: web.Request) -> web.Response:
        try:
            room_id = RoomID(request.query["room_id"])
        except KeyError:
            return web.Response(status=400, content_type="text/plain",
                                text="Room ID query param missing")
        return web.Response(status=200, content_type="text/html",
                            text=self.widget_tpl.render(codes=await self.get_codes(room_id)))

    async def get_json(self, request: web.Request) -> web.Response:
        try:
            room_id = RoomID(request.query["room_id"])
        except KeyError:
            return web.Response(status=400, content_type="application/json",
                                text='{"error": "Room  ID query param missing"}')
        return web.Response(status=200, content_type="application/json",
                            text=json.dumps(await self.get_codes(room_id)))
