"""Test Wyoming identity helpers."""

from __future__ import annotations

import logging

from homeassistant.components.wyoming.identity import (
    async_get_effective_context,
    get_identity_store,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant

from tests.common import MockUser


async def test_effective_context_with_mapping(
    hass: HomeAssistant,
    init_wyoming_intent: ConfigEntry,
    hass_admin_user: MockUser,
) -> None:
    """Test a mapped Wyoming identity impersonates a Home Assistant user."""
    store = get_identity_store(hass)
    store.async_set_mapping(init_wyoming_intent.entry_id, "Alice", hass_admin_user.id)

    original_context = Context(user_id="original-user", parent_id="parent", id="ctx-id")
    effective_context = await async_get_effective_context(
        hass,
        init_wyoming_intent.entry_id,
        original_context,
        "alice",
    )

    assert effective_context is not original_context
    assert effective_context.user_id == hass_admin_user.id
    assert effective_context.parent_id == original_context.parent_id
    assert effective_context.id == original_context.id


async def test_effective_context_missing_user_warned_once(
    hass: HomeAssistant,
    init_wyoming_intent: ConfigEntry,
    caplog,
) -> None:
    """Test missing mapped users fall back to the original context."""
    store = get_identity_store(hass)
    store.async_set_mapping(init_wyoming_intent.entry_id, "Alice", "missing-user")

    original_context = Context(user_id="original-user")

    with caplog.at_level(logging.WARNING):
        effective_context_1 = await async_get_effective_context(
            hass,
            init_wyoming_intent.entry_id,
            original_context,
            "alice",
        )
        effective_context_2 = await async_get_effective_context(
            hass,
            init_wyoming_intent.entry_id,
            original_context,
            "alice",
        )

    assert effective_context_1 is original_context
    assert effective_context_2 is original_context
    assert (
        caplog.text.count("Wyoming identity mapping for Alice points to missing user")
        == 1
    )
