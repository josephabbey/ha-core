"""Websocket API for interacting with the floor plan registry."""

# Area shapes are configured via the area_registry.

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import floor_plan_registry as fpr


def async_setup(hass: HomeAssistant) -> bool:
    """Enable the Floor Plan Registry views."""
    websocket_api.async_register_command(hass, websocket_list_floor_plans)
    websocket_api.async_register_command(hass, websocket_create_floor_plan)
    websocket_api.async_register_command(hass, websocket_delete_floor_plan)
    websocket_api.async_register_command(hass, websocket_update_floor_plan)
    return True


@websocket_api.websocket_command(
    {vol.Required("type"): "config/floor_plan_registry/list"}
)
@callback
def websocket_list_floor_plans(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle list floor plans command."""
    registry = fpr.async_get(hass)
    connection.send_result(
        msg["id"],
        [entry.json_fragment for entry in registry.async_list_floor_plans()],
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "config/floor_plan_registry/create",
        vol.Required("level"): int,
        vol.Optional("shape"): vol.Any(list[tuple[float, float]], None),
        vol.Optional("background_image"): vol.Any(str, None),
        vol.Optional("background_image_anchor"): vol.Any(tuple[float, float], None),
        vol.Optional("background_image_scale_x"): vol.Any(float, None),
        vol.Optional("background_image_scale_y"): vol.Any(float, None),
        vol.Optional("background_image_rotation"): vol.Any(float, None),
    }
)
@callback
def websocket_create_floor_plan(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle create floor plan command."""
    registry = fpr.async_get(hass)

    data = dict(msg)
    data.pop("type")
    data.pop("id")

    try:
        entry = registry.async_create(**data)
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_info", str(err))
    else:
        connection.send_result(msg["id"], entry.json_fragment)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "config/floor_plan_registry/delete",
        vol.Required("level"): int,
    }
)
@websocket_api.require_admin
@callback
def websocket_delete_floor_plan(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete floor plan command."""
    registry = fpr.async_get(hass)

    try:
        registry.async_delete(msg["level"])
    except KeyError:
        connection.send_error(
            msg["id"], "invalid_info", "Floor plan does not exist for that level."
        )
    else:
        connection.send_message(websocket_api.result_message(msg["id"], "success"))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "config/floor_plan_registry/update",
        vol.Required("level"): int,
        vol.Optional("shape"): vol.Any(list[tuple[float, float]], None),
        vol.Optional("background_image"): vol.Any(str, None),
        vol.Optional("background_image_anchor"): vol.Any(tuple[float, float], None),
        vol.Optional("background_image_scale_x"): vol.Any(float, None),
        vol.Optional("background_image_scale_y"): vol.Any(float, None),
        vol.Optional("background_image_rotation"): vol.Any(float, None),
    }
)
@websocket_api.require_admin
@callback
def websocket_update_floor_plan(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle update floor plan websocket command."""
    registry = fpr.async_get(hass)

    data = dict(msg)
    data.pop("type")
    data.pop("id")

    try:
        entry = registry.async_update(**data)
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_info", str(err))
    else:
        connection.send_result(msg["id"], entry.json_fragment)
