"""Websocket API for floor plan item registry."""

from __future__ import annotations

from homeassistant.core import HomeAssistant


def async_setup(hass: HomeAssistant) -> bool:
    """Enable the Floor Plan Item Registry views."""
    return True
