"""Controller: authenticates against Ecovacs and manages the legacy robots."""

from __future__ import annotations

from dataclasses import asdict
import logging

from deebot_client.api_client import ApiClient
from deebot_client.authentication import Authenticator, create_rest_config
from deebot_client.exceptions import (
    DeebotError,
    DeviceVerificationRequiredError,
    InvalidAuthenticationError,
)
from deebot_client.models import AccountCredentials
from deebot_client.util import md5
from deebot_client.util.continents import get_continent

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client

from .const import CONF_ACCOUNT_CREDENTIALS
from .device import XMPP_DOMAIN, XMPP_PORT, LegacyDevice, xmpp_host
from .xmpp_client import XmppClient

_LOGGER = logging.getLogger(__name__)


class LegacyController:
    """Manage the account session and all legacy devices."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the controller."""
        self._hass = hass
        self._entry = entry
        config = entry.data
        self._device_id: str = config[CONF_DEVICE_ID]
        self._continent = get_continent(config[CONF_COUNTRY])
        self.devices: list[LegacyDevice] = []

        self._authenticator = Authenticator(
            create_rest_config(
                aiohttp_client.async_get_clientsession(hass),
                device_id=self._device_id,
                alpha_2_country=config[CONF_COUNTRY],
            ),
            config[CONF_USERNAME],
            md5(config[CONF_PASSWORD]),
            account_credentials=(
                AccountCredentials(**account)
                if (account := config.get(CONF_ACCOUNT_CREDENTIALS))
                else None
            ),
        )
        self._unsubscribe_credentials = (
            self._authenticator.subscribe_account_credentials(self._store_credentials)
        )
        self._api_client = ApiClient(self._authenticator)

    async def _store_credentials(self, account: AccountCredentials) -> None:
        self._hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_ACCOUNT_CREDENTIALS: asdict(account)},
        )

    async def _password(self) -> str:
        """Return the XMPP password (renews the token when needed)."""
        credentials = await self._authenticator.authenticate()
        return f"0/{self._device_id[0:8]}/{credentials.token}"

    async def initialize(self) -> None:
        """Log in, discover the XMPP devices and start them."""
        try:
            devices = await self._api_client.get_devices()
            credentials = await self._authenticator.authenticate()
        except DeviceVerificationRequiredError as ex:
            raise ConfigEntryAuthFailed("Device verification required") from ex
        except InvalidAuthenticationError as ex:
            raise ConfigEntryAuthFailed("Invalid authentication") from ex
        except DeebotError as ex:
            raise ConfigEntryNotReady("Cannot reach the Ecovacs API") from ex

        def factory(device: LegacyDevice) -> XmppClient:
            return XmppClient(
                host=xmpp_host(self._continent),
                port=XMPP_PORT,
                domain=XMPP_DOMAIN,
                user=credentials.user_id,
                resource=self._device_id[0:8],
                password_provider=self._password,
                device_jid=device.device_jid,
                on_message=device.handle_message,
                on_connection_change=device.handle_connection_change,
            )

        for info in devices.xmpp:
            self.devices.append(LegacyDevice(dict(info), factory))
        if not self.devices:
            _LOGGER.warning("No legacy (XMPP) devices found in this Ecovacs account")
        for device in self.devices:
            device.start()

    async def teardown(self) -> None:
        """Stop everything."""
        self._unsubscribe_credentials()
        for device in self.devices:
            await device.stop()
        await self._authenticator.teardown()
