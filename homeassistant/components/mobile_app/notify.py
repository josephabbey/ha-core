"""Support for mobile_app push notifications."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from functools import partial
from http import HTTPStatus
import logging
from typing import Any

import aiohttp

from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_MESSAGE,
    ATTR_TARGET,
    ATTR_TITLE,
    ATTR_TITLE_DEFAULT,
    BaseNotificationService,
    NotifyEntity,
    NotifyEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_APP_DATA,
    ATTR_APP_ID,
    ATTR_APP_VERSION,
    ATTR_DEVICE_NAME,
    ATTR_OS_VERSION,
    ATTR_PUSH_RATE_LIMITS,
    ATTR_PUSH_RATE_LIMITS_ERRORS,
    ATTR_PUSH_RATE_LIMITS_MAXIMUM,
    ATTR_PUSH_RATE_LIMITS_RESETS_AT,
    ATTR_PUSH_RATE_LIMITS_SUCCESSFUL,
    ATTR_PUSH_TOKEN,
    ATTR_PUSH_URL,
    ATTR_WEBHOOK_ID,
    DATA_CONFIG_ENTRIES,
    DATA_NOTIFY,
    DATA_PUSH_CHANNEL,
    DOMAIN,
)
from .util import supports_push

_LOGGER = logging.getLogger(__name__)


def push_registrations(hass: HomeAssistant) -> dict[str, str]:
    """Return a dictionary of push enabled registrations."""
    targets = {}

    for webhook_id, entry in hass.data[DOMAIN][DATA_CONFIG_ENTRIES].items():
        if not supports_push(hass, webhook_id):
            continue

        targets[entry.data[ATTR_DEVICE_NAME]] = webhook_id

    return targets


def log_rate_limits(
    hass: HomeAssistant,
    device_name: str,
    resp: dict[str, Any],
    level: int = logging.INFO,
) -> None:
    """Output rate limit log line at given level."""
    if ATTR_PUSH_RATE_LIMITS not in resp:
        return

    rate_limits = resp[ATTR_PUSH_RATE_LIMITS]
    resets_at_dt = dt_util.parse_datetime(rate_limits[ATTR_PUSH_RATE_LIMITS_RESETS_AT])
    if resets_at_dt is None:
        return
    resets_at_delta = resets_at_dt - dt_util.utcnow()
    rate_limit_msg = (
        "mobile_app push notification rate limits for %s: "
        "%d sent, %d allowed, %d errors, "
        "resets in %s"
    )
    _LOGGER.log(
        level,
        rate_limit_msg,
        device_name,
        rate_limits[ATTR_PUSH_RATE_LIMITS_SUCCESSFUL],
        rate_limits[ATTR_PUSH_RATE_LIMITS_MAXIMUM],
        rate_limits[ATTR_PUSH_RATE_LIMITS_ERRORS],
        str(resets_at_delta).split(".", maxsplit=1)[0],
    )


async def async_get_service(
    hass: HomeAssistant,
    config: ConfigType,
    discovery_info: DiscoveryInfoType | None = None,
) -> MobileAppNotificationService:
    """Get the mobile_app notification service."""
    service = hass.data[DOMAIN][DATA_NOTIFY] = MobileAppNotificationService()
    return service


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up mobile app notify platform."""
    webhook_id = config_entry.data[CONF_WEBHOOK_ID]

    if not supports_push(hass, webhook_id):
        return

    async_add_entities([MobileAppNotifyEntity(config_entry)])


@callback
def _async_send_push_notification(
    hass: HomeAssistant,
    target: str,
    registration: Mapping[str, Any],
    data: dict[str, Any],
) -> None:
    """Send a push notification to a specific target."""
    local_push_channels = hass.data[DOMAIN][DATA_PUSH_CHANNEL]

    if target in local_push_channels:
        local_push_channels[target].async_send_notification(
            data,
            partial(_async_send_remote_message_target, hass, target, registration),
        )
        return

    # Test if local push only.
    if ATTR_PUSH_URL not in registration[ATTR_APP_DATA]:
        raise HomeAssistantError(
            f"Device with webhook id {target} not connected to local push notifications"
        )

    hass.async_create_task(
        _async_send_remote_message_target(hass, target, registration, data),
        eager_start=True,
    )


async def _async_send_remote_message_target(
    hass: HomeAssistant,
    target: str,
    registration: Mapping[str, Any],
    data: dict[str, Any],
) -> None:
    """Send a message to a target."""
    app_data = registration[ATTR_APP_DATA]
    push_token = app_data[ATTR_PUSH_TOKEN]
    push_url = app_data[ATTR_PUSH_URL]

    target_data = dict(data)
    target_data[ATTR_PUSH_TOKEN] = push_token

    reg_info = {
        ATTR_APP_ID: registration[ATTR_APP_ID],
        ATTR_APP_VERSION: registration[ATTR_APP_VERSION],
        ATTR_WEBHOOK_ID: target,
    }
    if ATTR_OS_VERSION in registration:
        reg_info[ATTR_OS_VERSION] = registration[ATTR_OS_VERSION]

    target_data["registration_info"] = reg_info

    try:
        async with asyncio.timeout(10):
            response = await async_get_clientsession(hass).post(
                push_url, json=target_data
            )
            result = await response.json()

        if response.status in (
            HTTPStatus.OK,
            HTTPStatus.CREATED,
            HTTPStatus.ACCEPTED,
        ):
            log_rate_limits(hass, registration[ATTR_DEVICE_NAME], result)
            return

        fallback_error = result.get("errorMessage", "Unknown error")
        fallback_message = (
            f"Internal server error, please try again later: {fallback_error}"
        )
        message = result.get("message", fallback_message)

        if "message" in result:
            if message[-1] not in [".", "?", "!"]:
                message += "."
            message += " This message is generated externally to Home Assistant."

        if response.status == HTTPStatus.TOO_MANY_REQUESTS:
            _LOGGER.warning(message)
            log_rate_limits(
                hass, registration[ATTR_DEVICE_NAME], result, logging.WARNING
            )
        else:
            _LOGGER.error(message)

    except TimeoutError:
        _LOGGER.error("Timeout sending notification to %s", push_url)
    except aiohttp.ClientError as err:
        _LOGGER.error("Error sending notification to %s: %r", push_url, err)


class MobileAppNotificationService(BaseNotificationService):
    """Implement the notification service for mobile_app."""

    @property
    def targets(self) -> dict[str, str]:
        """Return a dictionary of registered targets."""
        return push_registrations(self.hass)

    async def async_send_message(self, message: str = "", **kwargs: Any) -> None:
        """Send a message to the Lambda APNS gateway."""
        data = {ATTR_MESSAGE: message}

        # Remove default title from notifications.
        if (
            title_arg := kwargs.get(ATTR_TITLE)
        ) is not None and title_arg != ATTR_TITLE_DEFAULT:
            data[ATTR_TITLE] = title_arg
        if not (targets := kwargs.get(ATTR_TARGET)):
            targets = push_registrations(self.hass).values()

        if (data_arg := kwargs.get(ATTR_DATA)) is not None:
            data[ATTR_DATA] = data_arg

        failed_targets = []
        for target in targets:
            registration = self.hass.data[DOMAIN][DATA_CONFIG_ENTRIES][target].data

            try:
                _async_send_push_notification(self.hass, target, registration, data)
            except HomeAssistantError:
                failed_targets.append(target)

        if failed_targets:
            raise HomeAssistantError(
                f"Device(s) with webhook id(s) {', '.join(failed_targets)} not connected to local push notifications"
            )


class MobileAppNotifyEntity(NotifyEntity):
    """Representation of a mobile app notify entity."""

    _attr_has_entity_name = True
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the entity."""
        self._config_entry = config_entry
        self._attr_unique_id = config_entry.data[CONF_WEBHOOK_ID]
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, config_entry.data[ATTR_DEVICE_ID])},
        )

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a message."""
        data = {ATTR_MESSAGE: message}
        if title is not None:
            data[ATTR_TITLE] = title

        _async_send_push_notification(
            self.hass,
            self._config_entry.data[CONF_WEBHOOK_ID],
            self._config_entry.data,
            data,
        )
