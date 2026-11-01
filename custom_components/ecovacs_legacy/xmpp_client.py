"""Minimal asyncio XMPP client for legacy Ecovacs robots (no external deps)."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
import logging
import random
import ssl
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr

from .protocol import Command, find_ctl, local_name

_LOGGER = logging.getLogger(__name__)

NS_STREAM = "http://etherx.jabber.org/streams"
NS_SASL = "urn:ietf:params:xml:ns:xmpp-sasl"
NS_BIND = "urn:ietf:params:xml:ns:xmpp-bind"
NS_SESSION = "urn:ietf:params:xml:ns:xmpp-session"
NS_CTL = "com:ctl"
NS_PING = "urn:xmpp:ping"

PING_INTERVAL = 30
STEP_TIMEOUT = 20
MAX_BACKOFF = 300

MessageCallback = Callable[[str, ET.Element], None]
ConnectionCallback = Callable[[bool], None]
PasswordProvider = Callable[[], Awaitable[str]]


class XmppError(Exception):
    """Generic XMPP error."""


class XmppAuthError(XmppError):
    """Authentication was rejected by the server."""


class XmppClient:
    """XMPP client speaking the ``com:ctl`` protocol with a legacy robot."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        domain: str,
        user: str,
        resource: str,
        password_provider: PasswordProvider,
        device_jid: str,
        on_message: MessageCallback,
        on_connection_change: ConnectionCallback | None = None,
        tls: bool = True,
    ) -> None:
        """Initialize the client."""
        self._host = host
        self._port = port
        self._domain = domain
        self._user = user
        self._resource = resource
        self._password_provider = password_provider
        self.device_jid = device_jid
        self._on_message = on_message
        self._on_connection_change = on_connection_change
        self._tls = tls

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._queue: asyncio.Queue[ET.Element | None] = asyncio.Queue()
        self._parser: ET.XMLPullParser | None = None
        self._root: ET.Element | None = None
        self._depth = 0
        self._read_task: asyncio.Task[None] | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._ping_task: asyncio.Task[None] | None = None
        self._sent: dict[str, str] = {}
        self._iq_counter = 0
        self._verify_tls = True
        self.connected = False

    @property
    def jid(self) -> str:
        """Return the full JID used by this client."""
        return f"{self._user}@{self._domain}/{self._resource}"

    def start(self) -> None:
        """Start the connect/reconnect loop."""
        if self._run_task is None:
            self._run_task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        """Stop the client and close the connection."""
        task, self._run_task = self._run_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._close()

    async def send(self, command: Command) -> None:
        """Send a command to the robot."""
        if not self.connected or self._writer is None:
            raise ConnectionError("XMPP connection is not established")
        self._sent[command.id] = command.name
        while len(self._sent) > 200:
            self._sent.pop(next(iter(self._sent)))
        iq = (
            f"<iq id={quoteattr(self._next_id())} from={quoteattr(self.jid)} "
            f"to={quoteattr(self.device_jid)} type='set'>"
            f"<query xmlns='{NS_CTL}'>{command.to_xml()}</query></iq>"
        )
        await self._write(iq)

    async def connect_once(self) -> None:
        """Connect and complete the XMPP handshake (used by run loop and tests)."""
        await self._open()
        try:
            await self._handshake()
        except BaseException:
            await self._close()
            raise
        self._set_connected(True)

    async def dispatch_forever(self) -> None:
        """Dispatch incoming stanzas until the connection is closed."""
        self._ping_task = asyncio.get_running_loop().create_task(self._ping_loop())
        try:
            while (stanza := await self._queue.get()) is not None:
                try:
                    await self._handle_stanza(stanza)
                except Exception:
                    _LOGGER.exception("Error handling stanza")
        finally:
            self._ping_task.cancel()

    async def _run(self) -> None:
        backoff = 5.0
        while True:
            try:
                await self.connect_once()
                backoff = 5.0
                await self.dispatch_forever()
                _LOGGER.warning("XMPP connection closed by the server")
            except asyncio.CancelledError:
                raise
            except (
                OSError,
                ssl.SSLError,
                TimeoutError,
                XmppError,
                ET.ParseError,
            ) as err:
                _LOGGER.warning("XMPP connection error: %r", err)
            except Exception:
                _LOGGER.exception("Unexpected XMPP error")
            await self._close()
            await asyncio.sleep(backoff + random.uniform(0, 3))
            backoff = min(backoff * 2, MAX_BACKOFF)

    async def _open(self) -> None:
        self._queue = asyncio.Queue()
        self._sent.clear()
        # The server speaks plain XMPP and requires STARTTLS (no direct TLS)
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port), STEP_TIMEOUT
        )
        self._start_read_task()

    def _start_read_task(self) -> None:
        self._read_task = asyncio.get_running_loop().create_task(self._read_loop())

    async def _start_tls(self) -> None:
        """Upgrade the connection to TLS after the server sent <proceed/>."""
        assert self._writer is not None
        task, self._read_task = self._read_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        context = await asyncio.get_running_loop().run_in_executor(
            None, self._create_ssl_context
        )
        try:
            await self._writer.start_tls(
                context,
                server_hostname=self._host,
                ssl_handshake_timeout=STEP_TIMEOUT,
            )
        except ssl.SSLCertVerificationError as err:
            if not self._verify_tls:
                raise
            # Legacy Ecovacs XMPP servers are known for outdated certificates
            _LOGGER.warning(
                "Certificate verification of %s failed (%s), "
                "retrying without verification",
                self._host,
                err,
            )
            self._verify_tls = False
            raise ConnectionError("Retrying without certificate verification") from err
        self._reset_parser()
        self._start_read_task()

    def _create_ssl_context(self) -> ssl.SSLContext:
        if self._verify_tls:
            return ssl.create_default_context()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    async def _close(self) -> None:
        self._set_connected(False)
        for task in (self._read_task, self._ping_task):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        self._read_task = self._ping_task = None
        writer, self._writer, self._reader = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 5)
            except (OSError, TimeoutError, ssl.SSLError):
                pass

    def _set_connected(self, value: bool) -> None:
        if self.connected != value:
            self.connected = value
            if self._on_connection_change:
                try:
                    self._on_connection_change(value)
                except Exception:
                    _LOGGER.exception("Connection callback failed")

    def _next_id(self) -> str:
        self._iq_counter += 1
        return str(self._iq_counter)

    async def _write(self, data: str) -> None:
        if self._writer is None:
            raise ConnectionError("XMPP connection is not established")
        _LOGGER.debug(
            "XMPP >>> %s", "<auth ...redacted...>" if data.startswith("<auth") else data
        )
        self._writer.write(data.encode())
        await self._writer.drain()

    def _reset_parser(self) -> None:
        self._parser = ET.XMLPullParser(events=("start", "end"))
        self._root = None
        self._depth = 0

    async def _read_loop(self) -> None:
        assert self._reader is not None
        reader = self._reader
        try:
            while data := await reader.read(8192):
                self._feed(data)
        except (OSError, ssl.SSLError, ET.ParseError) as err:
            _LOGGER.debug("XMPP read error: %r", err)
        self._queue.put_nowait(None)

    def _feed(self, data: bytes) -> None:
        _LOGGER.debug("XMPP <<< %s", data.decode(errors="replace"))
        assert self._parser is not None
        self._parser.feed(data)
        for event, element in self._parser.read_events():
            if event == "start":
                self._depth += 1
                if self._depth == 1:
                    self._root = element
            else:
                if self._depth == 2:
                    self._queue.put_nowait(element)
                    if self._root is not None:
                        self._root.remove(element)
                elif self._depth == 1:
                    self._queue.put_nowait(None)
                self._depth -= 1

    async def _next_stanza(self, expected: str | None = None) -> ET.Element:
        stanza = await asyncio.wait_for(self._queue.get(), STEP_TIMEOUT)
        if stanza is None:
            raise ConnectionError("XMPP stream closed during handshake")
        if expected and local_name(stanza.tag) != expected:
            raise XmppError(f"Expected <{expected}>, got <{local_name(stanza.tag)}>")
        return stanza

    async def _open_stream(self) -> ET.Element:
        self._reset_parser()
        await self._write(
            "<?xml version='1.0'?>"
            f"<stream:stream to={quoteattr(self._domain)} xmlns='jabber:client' "
            f"xmlns:stream='{NS_STREAM}' version='1.0'>"
        )
        return await self._next_stanza("features")

    async def _handshake(self) -> None:
        features = await self._open_stream()
        if self._tls and any(local_name(f.tag) == "starttls" for f in features):
            await self._write("<starttls xmlns='urn:ietf:params:xml:ns:xmpp-tls'/>")
            await self._next_stanza("proceed")
            await self._start_tls()
            features = await self._open_stream()
        mechanisms = [
            m.text for m in features.iter() if local_name(m.tag) == "mechanism"
        ]
        if mechanisms and "PLAIN" not in mechanisms:
            raise XmppError(f"PLAIN SASL not offered by the server: {mechanisms}")

        password = await self._password_provider()
        token = base64.b64encode(f"\0{self._user}\0{password}".encode()).decode()
        await self._write(
            f"<auth xmlns='{NS_SASL}' mechanism='PLAIN'>{token}</auth>"
        )
        result = await self._next_stanza()
        if local_name(result.tag) != "success":
            raise XmppAuthError(f"SASL authentication failed: <{local_name(result.tag)}>")

        features = await self._open_stream()
        await self._write(
            f"<iq type='set' id='bind1'><bind xmlns='{NS_BIND}'>"
            f"<resource>{self._resource}</resource></bind></iq>"
        )
        bind = await self._next_stanza("iq")
        if bind.get("type") != "result":
            raise XmppError("Resource binding failed")
        if any(local_name(f.tag) == "session" for f in features):
            await self._write(
                f"<iq type='set' id='sess1'><session xmlns='{NS_SESSION}'/></iq>"
            )
            await self._next_stanza("iq")
        await self._write("<presence/>")

    async def _ping_loop(self) -> None:
        while True:
            try:
                await self._write(
                    f"<iq id={quoteattr('ping' + self._next_id())} "
                    f"from={quoteattr(self.jid)} to={quoteattr(self.device_jid)} "
                    f"type='get'><query xmlns='{NS_PING}'/></iq>"
                )
            except (OSError, ConnectionError):
                return
            await asyncio.sleep(PING_INTERVAL)

    async def _handle_stanza(self, stanza: ET.Element) -> None:
        if local_name(stanza.tag) != "iq":
            return
        kind = stanza.get("type")
        if kind in ("set", "result"):
            ctl = find_ctl(stanza)
            if ctl is None:
                return
            name = self._sent.pop(ctl.get("id", ""), None) or ctl.get("td")
            if name:
                self._on_message(name, ctl)
        elif kind == "get":
            if any(local_name(c.tag) == "ping" for c in stanza):
                await self._write(
                    f"<iq type='result' id={quoteattr(stanza.get('id', ''))} "
                    f"to={quoteattr(stanza.get('from', ''))}/>"
                )
        elif kind == "error":
            _LOGGER.debug("XMPP error stanza: %s", ET.tostring(stanza, "unicode"))


__all__: list[Any] = ["XmppClient", "XmppError", "XmppAuthError"]
