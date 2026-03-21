"""Wyoming Websocket API."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .identity import get_identity_names, get_identity_store
from .models import DomainDataItem

_LOGGER = logging.getLogger(__name__)


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register the websocket API."""
    websocket_api.async_register_command(hass, websocket_info)
    websocket_api.async_register_command(hass, websocket_identity_list)
    websocket_api.async_register_command(hass, websocket_identity_mapping_list)
    websocket_api.async_register_command(hass, websocket_identity_mapping_set)
    websocket_api.async_register_command(hass, websocket_identity_mapping_delete)


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "wyoming/info"})
def websocket_info(
    hass: HomeAssistant,
    connection: websocket_api.connection.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List service information for Wyoming all config entries."""
    entry_items: dict[str, DomainDataItem] = hass.data.get(DOMAIN, {})

    connection.send_result(
        msg["id"],
        {
            "info": {
                entry_id: item.service.info.to_dict()
                for entry_id, item in entry_items.items()
            }
        },
    )


@callback
def _get_entry_item(
    hass: HomeAssistant, entry_id: str
) -> tuple[ConfigEntry | None, DomainDataItem | None]:
    """Return the config entry and domain data item."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        return (None, None)

    return (entry, hass.data.get(DOMAIN, {}).get(entry_id))


@callback
@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "wyoming/identity/list",
        vol.Required("entry_id"): str,
    }
)
def websocket_identity_list(
    hass: HomeAssistant,
    connection: websocket_api.connection.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List known identities reported by a Wyoming service."""
    entry, item = _get_entry_item(hass, msg["entry_id"])
    if entry is None or item is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Config entry not found"
        )
        return

    connection.send_result(
        msg["id"],
        {"identities": get_identity_names(item.service.info)},
    )


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "wyoming/identity_mapping/list",
        vol.Required("entry_id"): str,
    }
)
async def websocket_identity_mapping_list(
    hass: HomeAssistant,
    connection: websocket_api.connection.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List identity mappings for a Wyoming config entry."""
    entry, _ = _get_entry_item(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Config entry not found"
        )
        return

    store = get_identity_store(hass)
    mappings = []
    for mapping in store.async_list_mappings(entry.entry_id):
        user = await hass.auth.async_get_user(mapping.user_id)
        mappings.append(
            {
                "identity_name": mapping.identity_name,
                "user_id": mapping.user_id,
                "user_name": user.name if user is not None else None,
            }
        )

    connection.send_result(msg["id"], {"mappings": mappings})


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "wyoming/identity_mapping/set",
        vol.Required("entry_id"): str,
        vol.Required("identity_name"): vol.All(cv.string, vol.Length(min=1)),
        vol.Required("user_id"): cv.string,
    }
)
async def websocket_identity_mapping_set(
    hass: HomeAssistant,
    connection: websocket_api.connection.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set an identity mapping for a Wyoming config entry."""
    entry, _ = _get_entry_item(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Config entry not found"
        )
        return

    identity_name = msg["identity_name"].strip()
    if not identity_name:
        connection.send_error(
            msg["id"], websocket_api.ERR_INVALID_FORMAT, "Identity name cannot be empty"
        )
        return

    if await hass.auth.async_get_user(msg["user_id"]) is None:
        connection.send_error(msg["id"], "user_not_found", "User not found")
        return

    store = get_identity_store(hass)
    store.async_set_mapping(entry.entry_id, identity_name, msg["user_id"])
    connection.send_result(msg["id"])


@callback
@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "wyoming/identity_mapping/delete",
        vol.Required("entry_id"): str,
        vol.Required("identity_name"): vol.All(cv.string, vol.Length(min=1)),
    }
)
def websocket_identity_mapping_delete(
    hass: HomeAssistant,
    connection: websocket_api.connection.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete an identity mapping for a Wyoming config entry."""
    entry, _ = _get_entry_item(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Config entry not found"
        )
        return

    store = get_identity_store(hass)
    if not store.async_delete_mapping(entry.entry_id, msg["identity_name"]):
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Identity mapping not found"
        )
        return

    connection.send_result(msg["id"])
