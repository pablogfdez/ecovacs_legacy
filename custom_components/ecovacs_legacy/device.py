"""Legacy (XMPP) Ecovacs robot device."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from typing import Any
from xml.etree import ElementTree as ET

from . import protocol
from .protocol import Command, RobotState
from .xmpp_client import XmppClient

_LOGGER = logging.getLogger(__name__)

XMPP_DOMAIN = "ecouser.net"
XMPP_PORT = 5223
REFRESH_INTERVAL = 60
FULL_REFRESH_EVERY = 30


def xmpp_host(continent: str) -> str:
    """Return the XMPP server host for a continent."""
    return f"msg-{continent}.ecouser.net"


class LegacyDevice:
    """A robot reachable over XMPP."""

    def __init__(
        self,
        info: dict[str, Any],
        client_factory: Callable[[LegacyDevice], XmppClient],
    ) -> None:
        """Initialize the device from the Ecovacs API device info."""
        self.info = info
        self.did: str = info["did"]
        self.name: str = info.get("nick") or self.did
        self.model: str | None = info.get("deviceName")
        self.state = RobotState()
        self._listeners: list[Callable[[], None]] = []
        self._refresh_task: asyncio.Task[None] | None = None
        self.client = client_factory(self)

    @property
    def device_jid(self) -> str:
        """Return the JID of the robot."""
        return f"{self.did}@{self.info['class']}.ecorobot.net/atom"

    @property
    def available(self) -> bool:
        """Return True while the XMPP connection is established."""
        return self.client.connected

    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a state listener and return the unsubscribe function."""
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

    def _notify(self) -> None:
        for callback in list(self._listeners):
            callback()

    def start(self) -> None:
        """Start the connection."""
        self.client.start()

    async def stop(self) -> None:
        """Stop the connection."""
        if self._refresh_task:
            self._refresh_task.cancel()
            self._refresh_task = None
        await self.client.stop()

    def handle_message(self, name: str, ctl: ET.Element) -> None:
        """Handle a message from the robot."""
        _LOGGER.debug("%s: message %s: %s", self.did, name, ET.tostring(ctl, "unicode"))
        if self.state.apply(name, ctl):
            self._notify()
        else:
            _LOGGER.debug("%s: unhandled message %s", self.did, name)

    def handle_connection_change(self, connected: bool) -> None:
        """Handle XMPP connection state changes."""
        if self._refresh_task:
            self._refresh_task.cancel()
            self._refresh_task = None
        if connected:
            self._refresh_task = asyncio.get_running_loop().create_task(
                self._refresh_loop()
            )
        self._notify()

    async def _refresh_loop(self) -> None:
        count = 0
        while True:
            commands = (
                protocol.initial_commands()
                if count % FULL_REFRESH_EVERY == 0
                else [
                    protocol.raw("GetCleanState"),
                    protocol.raw("GetChargeState"),
                    protocol.raw("GetBatteryInfo"),
                ]
            )
            for command in commands:
                try:
                    await self.client.send(command)
                except (OSError, ConnectionError):
                    return
            count += 1
            await asyncio.sleep(REFRESH_INTERVAL)

    async def send(self, command: Command) -> None:
        """Send a command to the robot."""
        await self.client.send(command)
