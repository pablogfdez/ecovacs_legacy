"""Probe a legacy Ecovacs robot (e.g. Deebot OZMO 930) over XMPP, outside Home Assistant.

Usage (password via environment variable, never on the command line):

    pip install deebot-client aiohttp
    set ECOVACS_PASSWORD=...            (PowerShell: $env:ECOVACS_PASSWORD="...")
    python scripts/xmpp_probe.py --username you@mail.com --country ES [--device-id ABCD1234] [--seconds 40]

It logs in, lists the XMPP devices, connects to the XMPP server, requests the whole
robot state and prints every raw stanza so protocol issues can be diagnosed.
Attach the output (without credentials) to bug reports.
"""

import argparse
import asyncio
import logging
import os
from pathlib import Path
import random
import string
import sys
import types
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ecovacs_legacy"
package = types.ModuleType("ecovacs_legacy")
package.__path__ = [str(ROOT)]
sys.modules["ecovacs_legacy"] = package

import aiohttp  # noqa: E402
from deebot_client.api_client import ApiClient  # noqa: E402
from deebot_client.authentication import Authenticator, create_rest_config  # noqa: E402
from deebot_client.exceptions import DeviceVerificationRequiredError  # noqa: E402
from deebot_client.util import md5  # noqa: E402
from deebot_client.util.continents import get_continent  # noqa: E402
from ecovacs_legacy import protocol  # noqa: E402
from ecovacs_legacy.device import (  # noqa: E402
    XMPP_DOMAIN,
    XMPP_PORT,
    LegacyDevice,
    xmpp_host,
)
from ecovacs_legacy.xmpp_client import XmppClient  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--username", required=True)
    parser.add_argument("--country", required=True, help="ISO alpha-2 code, e.g. ES")
    parser.add_argument("--device-id", help="client device id (reuse HA's to skip verification)")
    parser.add_argument("--seconds", type=int, default=40)
    parser.add_argument("--command", action="append", default=[], help="extra raw command, e.g. GetCleanSum")
    args = parser.parse_args()

    password = os.environ.get("ECOVACS_PASSWORD") or input("Password: ")
    device_id = args.device_id or "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("ecovacs_legacy").setLevel(logging.DEBUG)

    async with aiohttp.ClientSession() as session:
        auth = Authenticator(
            create_rest_config(session, device_id=device_id, alpha_2_country=args.country),
            args.username,
            md5(password),
        )
        try:
            credentials = await auth.authenticate()
        except DeviceVerificationRequiredError:
            await auth.request_device_verification_code()
            await auth.verify_device(input("Verification code sent by e-mail: ").strip())
            credentials = await auth.authenticate()
        devices = await ApiClient(auth).get_devices()
        print(f"MQTT devices: {len(devices.mqtt)}  XMPP devices: {len(devices.xmpp)}  "
              f"unsupported: {len(devices.not_supported)}")
        for info in devices.xmpp:
            print("XMPP device:", {k: info.get(k) for k in ("nick", "deviceName", "class", "company")})
        if not devices.xmpp:
            return

        continent = get_continent(args.country)

        async def password_provider() -> str:
            creds = await auth.authenticate()
            return f"0/{device_id[0:8]}/{creds.token}"

        def factory(device: LegacyDevice) -> XmppClient:
            return XmppClient(
                host=xmpp_host(continent),
                port=XMPP_PORT,
                domain=XMPP_DOMAIN,
                user=credentials.user_id,
                resource=device_id[0:8],
                password_provider=password_provider,
                device_jid=device.device_jid,
                on_message=lambda name, ctl: (
                    print(f"<< {name}: {ET.tostring(ctl, 'unicode')}"),
                    device.handle_message(name, ctl),
                ),
            )

        device = LegacyDevice(dict(devices.xmpp[0]), factory)
        await device.client.connect_once()
        print("XMPP connected and authenticated")
        dispatch = asyncio.create_task(device.client.dispatch_forever())
        for command in [*protocol.initial_commands(), *(protocol.raw(c) for c in args.command)]:
            await device.client.send(command)
        await asyncio.sleep(args.seconds)
        dispatch.cancel()
        await device.client.stop()
        print("Final state:", device.state)
        await auth.teardown()


if __name__ == "__main__":
    asyncio.run(main())
