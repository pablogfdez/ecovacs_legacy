"""Test the XMPP client against a fake legacy Ecovacs XMPP server."""

import asyncio
import base64
import re

import pytest
from ecovacs_legacy import protocol
from ecovacs_legacy.xmpp_client import XmppAuthError, XmppClient

STREAM = (
    "<?xml version='1.0'?><stream:stream xmlns='jabber:client' "
    "xmlns:stream='http://etherx.jabber.org/streams' id='1' from='ecouser.net' "
    "version='1.0'>"
)


class FakeServer:
    def __init__(self, password="0/res/token"):
        self.password = password
        self.received: list[str] = []
        self.server = None
        self.writers = []

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def _handle(self, reader, writer):
        self.writers.append(writer)
        authenticated = False
        while data := await reader.read(8192):
            text = data.decode()
            self.received.append(text)
            if "<stream:stream" in text:
                writer.write(STREAM.encode())
                if not authenticated:
                    writer.write(
                        b"<stream:features><mechanisms xmlns='urn:ietf:params:xml:ns:xmpp-sasl'>"
                        b"<mechanism>PLAIN</mechanism></mechanisms></stream:features>"
                    )
                else:
                    writer.write(
                        b"<stream:features><bind xmlns='urn:ietf:params:xml:ns:xmpp-bind'/>"
                        b"<session xmlns='urn:ietf:params:xml:ns:xmpp-session'/></stream:features>"
                    )
            if "<auth" in text:
                token = re.search(r">([^<]+)</auth>", text).group(1)
                decoded = base64.b64decode(token).split(b"\0")
                if decoded[2].decode() == self.password:
                    authenticated = True
                    writer.write(b"<success xmlns='urn:ietf:params:xml:ns:xmpp-sasl'/>")
                else:
                    writer.write(b"<failure xmlns='urn:ietf:params:xml:ns:xmpp-sasl'/>")
            if "id='bind1'" in text:
                writer.write(
                    b"<iq type='result' id='bind1'><bind xmlns='urn:ietf:params:xml:ns:xmpp-bind'>"
                    b"<jid>u@ecouser.net/res</jid></bind></iq>"
                )
            if "id='sess1'" in text:
                writer.write(b"<iq type='result' id='sess1'/>")
            if m := re.search(r"<ctl td=\"GetBatteryInfo\" id=\"(\d+)\"", text):
                writer.write(
                    (
                        "<iq type='result' from='d@126.ecorobot.net/atom'>"
                        f"<query xmlns='com:ctl'><ctl id='{m.group(1)}' ret='ok'>"
                        "<battery power='77'/></ctl></query></iq>"
                    ).encode()
                )
            await writer.drain()

    async def push(self, xml: str):
        self.writers[-1].write(xml.encode())
        await self.writers[-1].drain()

    async def close(self):
        self.server.close()


def make_client(port, messages, password="0/res/token"):
    async def provider():
        return password

    return XmppClient(
        host="127.0.0.1",
        port=port,
        domain="ecouser.net",
        user="u",
        resource="res",
        password_provider=provider,
        device_jid="d@126.ecorobot.net/atom",
        on_message=lambda name, ctl: messages.append((name, ctl)),
        tls=False,
    )


async def test_handshake_command_and_push():
    server = FakeServer()
    port = await server.start()
    messages: list = []
    client = make_client(port, messages)
    await client.connect_once()
    assert client.connected
    task = asyncio.create_task(client.dispatch_forever())

    await client.send(protocol.Command("GetBatteryInfo"))
    await server.push(
        "<iq type='set'><query xmlns='com:ctl'><ctl td='ChargeState'>"
        "<charge type='Going'/></ctl></query></iq>"
    )
    for _ in range(50):
        if len(messages) >= 2:
            break
        await asyncio.sleep(0.02)

    names = [n for n, _ in messages]
    assert sorted(names) == ["ChargeState", "GetBatteryInfo"]
    state = protocol.RobotState()
    for name, ctl in messages:
        state.apply(name, ctl)
    assert state.battery == 77 and state.charge == "returning"

    await client.stop()
    task.cancel()
    await server.close()


async def test_auth_failure():
    server = FakeServer(password="other")
    port = await server.start()
    client = make_client(port, [])
    with pytest.raises(XmppAuthError):
        await client.connect_once()
    assert not client.connected
    await server.close()


async def test_server_close_ends_dispatch():
    server = FakeServer()
    port = await server.start()
    client = make_client(port, [])
    await client.connect_once()
    task = asyncio.create_task(client.dispatch_forever())
    server.writers[-1].close()
    await asyncio.wait_for(task, 5)
    await client.stop()
    await server.close()
