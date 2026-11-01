"""Config flow for Ecovacs Legacy (XMPP)."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import random
import string
from typing import Any

from aiohttp import ClientError
from deebot_client.api_client import ApiClient
from deebot_client.authentication import Authenticator, create_rest_config
from deebot_client.exceptions import (
    DeviceVerificationRequiredError,
    InvalidAuthenticationError,
    InvalidVerificationCodeError,
)
from deebot_client.util import md5

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.helpers import aiohttp_client, selector

from .const import CONF_VERIFICATION_CODE, DOMAIN

try:
    import probatio as vol  # Home Assistant >= the voluptuous replacement
except ImportError:  # pragma: no cover
    import voluptuous as vol

_LOGGER = logging.getLogger(__name__)


def _text(password: bool = False) -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(
            type=selector.TextSelectorType.PASSWORD
            if password
            else selector.TextSelectorType.TEXT
        )
    )


class EcovacsLegacyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    _input: dict[str, Any]
    _authenticator: Authenticator | None = None
    _device_id: str

    async def _async_authenticate(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Log in. Raises DeviceVerificationRequiredError when a code is needed."""
        await self._async_teardown()
        self._input = user_input
        device_id = user_input.get(CONF_DEVICE_ID) or "".join(
            random.choices(string.ascii_uppercase + string.digits, k=8)
        )
        self._device_id = user_input[CONF_DEVICE_ID] = device_id
        self._authenticator = Authenticator(
            create_rest_config(
                aiohttp_client.async_get_clientsession(self.hass),
                device_id=device_id,
                alpha_2_country=user_input[CONF_COUNTRY],
            ),
            user_input[CONF_USERNAME],
            md5(user_input[CONF_PASSWORD]),
        )
        return await self._async_validate()

    async def _async_validate(self) -> dict[str, str]:
        assert self._authenticator is not None
        try:
            await self._authenticator.authenticate()
            devices = await ApiClient(self._authenticator).get_devices()
        except DeviceVerificationRequiredError:
            raise
        except ClientError:
            return {"base": "cannot_connect"}
        except InvalidAuthenticationError:
            return {"base": "invalid_auth"}
        except Exception:
            _LOGGER.exception("Unexpected exception during login")
            return {"base": "unknown"}
        if not devices.xmpp:
            return {"base": "no_legacy_devices"}
        return {}

    async def _async_teardown(self) -> None:
        if self._authenticator is not None:
            await self._authenticator.teardown()
            self._authenticator = None

    def _finish(self) -> ConfigFlowResult:
        self.hass.async_create_background_task(
            self._async_teardown(), "ecovacs_legacy_flow_teardown"
        )
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates=self._input
            )
        return self.async_create_entry(title=self._input[CONF_USERNAME], data=self._input)

    async def _login_or_verify(
        self, user_input: dict[str, Any]
    ) -> tuple[ConfigFlowResult | None, dict[str, str]]:
        try:
            errors = await self._async_authenticate(user_input)
        except DeviceVerificationRequiredError:
            assert self._authenticator is not None
            try:
                await self._authenticator.request_device_verification_code()
            except ClientError:
                return None, {"base": "cannot_connect"}
            return await self.async_step_device_verification(), {}
        return (self._finish() if not errors else None), errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input:
            self._async_abort_entries_match({CONF_USERNAME: user_input[CONF_USERNAME]})
            result, errors = await self._login_or_verify(dict(user_input))
            if result:
                return result

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): _text(),
                vol.Required(CONF_PASSWORD): _text(True),
                vol.Required(CONF_COUNTRY): selector.CountrySelector(),
                vol.Optional(CONF_DEVICE_ID): _text(),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or {CONF_COUNTRY: self.hass.config.country}
            ),
            errors=errors,
        )

    async def async_step_device_verification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the verification code sent by Ecovacs."""
        errors: dict[str, str] = {}
        if user_input and self._authenticator:
            try:
                await self._authenticator.verify_device(
                    user_input[CONF_VERIFICATION_CODE]
                )
            except InvalidVerificationCodeError:
                errors["base"] = "invalid_verification_code"
            except ClientError:
                errors["base"] = "cannot_connect"
            else:
                errors = await self._async_validate()
                if not errors:
                    return self._finish()
        return self.async_show_form(
            step_id="device_verification",
            data_schema=vol.Schema({vol.Required(CONF_VERIFICATION_CODE): _text()}),
            description_placeholders={CONF_USERNAME: self._input[CONF_USERNAME]},
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication."""
        self._input = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again."""
        errors: dict[str, str] = {}
        if user_input:
            result, errors = await self._login_or_verify(self._input | user_input)
            if result:
                return result
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _text(True)}),
            description_placeholders={CONF_USERNAME: self._input[CONF_USERNAME]},
            errors=errors,
        )
