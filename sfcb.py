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
from typing import Dict, List, NamedTuple, Pattern
from pkg_resources import resource_string
import re
import asyncio
import json

from aiohttp import web
from jinja2 import Template

from mautrix.types import RoomID, UserID, StateEvent, EventType
from mautrix.errors import MNotFound

from maubot import Plugin, MessageEvent
from maubot.handlers import command, event

STATE_SWITCH_FRIEND_CODES = EventType("xyz.maubot.switch.friendcodes", EventType.Class.STATE)

Profile = NamedTuple("Profile", displayname=str, avatar_url=str)


class SwitchFriendCodeBot(Plugin):
    cache: Dict[RoomID, Dict[UserID, List[int]]]
    profiles: Dict[RoomID, Dict[UserID, Profile]]
    cache_lock: Dict[RoomID, asyncio.Lock]
    widget_tpl: Template
    code_regex: Pattern = re.compile(r"^(?:SW-)?([0-9]{4})-?([0-9]{4})-?([0-9]{4})$")

    async def start(self) -> None:
        await super().start()
        self.cache = {}
        self.profiles = {}
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

    async def get_codes(self, room_id: RoomID) -> Dict[UserID, List[int]]:
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

    async def get_profiles(self, room_id: RoomID) -> Dict[UserID, Profile]:
        async with self._lock(room_id):
            try:
                return self.profiles[room_id]
            except KeyError:
                pass

            try:
                states = await self.client.get_state(room_id)
            except MNotFound:
                return {}
            profiles = {}
            for evt in states:
                if evt.type == EventType.ROOM_MEMBER:
                    profiles[UserID(evt.state_key)] = Profile(
                        displayname=evt.content.displayname, avatar_url=evt.content.avatar_url)
            self.profiles[room_id] = profiles
            return profiles

    @command.new("code", help="Share your Switch friend code")
    @command.argument("code", required=True)
    async def set_code(self, evt: MessageEvent, code: str) -> None:
        match = self.code_regex.fullmatch(code)
        try:
            data = [int(match.group(1)),int(match.group(2)), int(match.group(3))]
        except (AttributeError, IndexError, ValueError):
            await evt.reply("That does not look like a valid Switch friend code")
            return
        cache = await self.get_codes(evt.room_id)
        cache[evt.sender] = data
        await self.client.send_state_event(room_id=evt.room_id,
                                           event_type=STATE_SWITCH_FRIEND_CODES,
                                           content=cache)
        await evt.mark_read()

    @event.on(STATE_SWITCH_FRIEND_CODES)
    async def handle_code(self, evt: StateEvent) -> None:
        async with self._lock(evt.room_id):
            self.cache[evt.room_id] = evt.content.serialize()

    @event.on(EventType.ROOM_MEMBER)
    async def handle_membership(self, evt: StateEvent) -> None:
        async with self._lock(evt.room_id):
            self.profiles[evt.room_id][UserID(evt.state_key)] = Profile(
                displayname=evt.content.displayname, avatar_url=evt.content.avatar_url)

    def _get_download_url(self, mxc: str) -> str:
        return (f"{self.client.api.base_url}/_matrix/media/r0/thumbnail/{mxc[6:]}"
                f"?width=16&height=16&method=crop")

    async def get_widget(self, request: web.Request) -> web.Response:
        try:
            room_id = RoomID(request.query["room_id"])
        except KeyError:
            return web.Response(status=400, content_type="text/plain",
                                text="Room ID query param missing")
        return web.Response(status=200, content_type="text/html",
                            text=self.widget_tpl.render(codes=await self.get_codes(room_id),
                                                        profiles=await self.get_profiles(room_id),
                                                        get_url=self._get_download_url))

    async def get_json(self, request: web.Request) -> web.Response:
        try:
            room_id = RoomID(request.query["room_id"])
        except KeyError:
            return web.Response(status=400, content_type="application/json",
                                text='{"error": "Room  ID query param missing"}')
        return web.Response(status=200, content_type="application/json",
                            text=json.dumps(await self.get_codes(room_id)))
