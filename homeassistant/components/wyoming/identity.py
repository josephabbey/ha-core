"""Identity mapping helpers for the Wyoming integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DATA_IDENTITY_STORE, STORAGE_KEY_IDENTITY_MAPPINGS

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_SAVE_DELAY = 10


@dataclass(slots=True)
class WyomingIdentityMapping:
    """A speaker identity to Home Assistant user mapping."""

    identity_name: str
    user_id: str


class WyomingIdentityStore:
    """Persistent storage for Wyoming identity mappings."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize storage."""
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, _STORAGE_VERSION, STORAGE_KEY_IDENTITY_MAPPINGS
        )
        self._data: dict[str, dict[str, dict[str, str]]] = {}
        self._warned_missing_users: set[tuple[str, str]] = set()

    async def async_setup(self) -> None:
        """Load mappings from storage."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            self._data = {}
            return

        items = stored.get("items")
        if not isinstance(items, dict):
            _LOGGER.warning("Invalid Wyoming identity mapping storage, ignoring data")
            self._data = {}
            return

        data: dict[str, dict[str, dict[str, str]]] = {}
        for entry_id, entry_data in items.items():
            if not isinstance(entry_id, str) or not isinstance(entry_data, dict):
                _LOGGER.warning(
                    "Invalid Wyoming identity mapping entry, ignoring data for %s",
                    entry_id,
                )
                continue

            mappings = entry_data.get("mappings")
            if not isinstance(mappings, dict):
                continue

            validated_mappings: dict[str, dict[str, str]] = {}
            for normalized_name, mapping in mappings.items():
                if (
                    not isinstance(normalized_name, str)
                    or not isinstance(mapping, dict)
                    or not isinstance(mapping.get("identity_name"), str)
                    or not isinstance(mapping.get("user_id"), str)
                ):
                    _LOGGER.warning(
                        "Invalid Wyoming identity mapping for %s, ignoring",
                        entry_id,
                    )
                    continue

                validated_mappings[normalized_name] = {
                    "identity_name": mapping["identity_name"],
                    "user_id": mapping["user_id"],
                }

            if validated_mappings:
                data[entry_id] = {"mappings": validated_mappings}

        self._data = data

    @callback
    def async_list_mappings(self, entry_id: str) -> list[WyomingIdentityMapping]:
        """Return mappings for a config entry."""
        mappings = self._data.get(entry_id, {}).get("mappings", {})
        return sorted(
            [
                WyomingIdentityMapping(
                    identity_name=mapping["identity_name"],
                    user_id=mapping["user_id"],
                )
                for mapping in mappings.values()
            ],
            key=lambda mapping: mapping.identity_name.casefold(),
        )

    @callback
    def async_set_mapping(self, entry_id: str, identity_name: str, user_id: str) -> None:
        """Store a mapping for a config entry."""
        identity_name = identity_name.strip()
        normalized_name = normalize_identity_name(identity_name)
        entry = self._data.setdefault(entry_id, {"mappings": {}})
        entry["mappings"][normalized_name] = {
            "identity_name": identity_name,
            "user_id": user_id,
        }
        self._warned_missing_users.discard((entry_id, user_id))
        self._store.async_delay_save(self._async_get_storage_data, _SAVE_DELAY)

    @callback
    def async_delete_mapping(self, entry_id: str, identity_name: str) -> bool:
        """Delete a mapping for a config entry."""
        normalized_name = normalize_identity_name(identity_name)
        entry = self._data.get(entry_id)
        if entry is None:
            return False

        mapping = entry["mappings"].pop(normalized_name, None)
        if mapping is None:
            return False

        self._warned_missing_users.discard((entry_id, mapping["user_id"]))

        if not entry["mappings"]:
            self._data.pop(entry_id, None)

        self._store.async_delay_save(self._async_get_storage_data, _SAVE_DELAY)
        return True

    async def async_resolve_user_id(
        self, entry_id: str, identity_name: str | None
    ) -> str | None:
        """Resolve a Home Assistant user id from an identity name."""
        if not identity_name:
            return None

        normalized_name = normalize_identity_name(identity_name)
        mapping = self._data.get(entry_id, {}).get("mappings", {}).get(normalized_name)
        if mapping is None:
            _LOGGER.debug(
                "No Wyoming identity mapping found for %s on entry %s",
                identity_name,
                entry_id,
            )
            return None

        user_id = mapping["user_id"]
        if await self.hass.auth.async_get_user(user_id) is None:
            warning_key = (entry_id, user_id)
            if warning_key not in self._warned_missing_users:
                self._warned_missing_users.add(warning_key)
                _LOGGER.warning(
                    "Wyoming identity mapping for %s points to missing user %s",
                    mapping["identity_name"],
                    user_id,
                )
            return None

        _LOGGER.debug(
            "Resolved Wyoming identity %s on entry %s to user %s",
            mapping["identity_name"],
            entry_id,
            user_id,
        )
        return user_id

    @callback
    def _async_get_storage_data(self) -> dict[str, Any]:
        """Return serializable storage data."""
        return {"items": self._data}


def normalize_identity_name(identity_name: str) -> str:
    """Normalize an identity name for lookups."""
    return identity_name.strip().casefold()


async def async_get_effective_context(
    hass: HomeAssistant,
    entry_id: str,
    context: Context,
    identity_name: str | None,
) -> Context:
    """Return a context impersonating the mapped user when available."""
    if not identity_name:
        return context

    _LOGGER.debug(
        "Received Wyoming identity %s for entry %s", identity_name, entry_id
    )
    store = get_identity_store(hass)
    user_id = await store.async_resolve_user_id(entry_id, identity_name)
    if user_id is None or user_id == context.user_id:
        return context

    effective_context = Context(
        user_id=user_id,
        parent_id=context.parent_id,
        id=context.id,
    )
    effective_context.origin_event = context.origin_event
    _LOGGER.debug(
        "Applying mapped Wyoming user %s for identity %s on entry %s",
        user_id,
        identity_name,
        entry_id,
    )
    return effective_context


def get_identity_names(info: Any) -> list[str]:
    """Return enrolled identity names reported by a Wyoming info object."""
    names: list[str] = []
    seen: set[str] = set()

    for program in getattr(info, "identity", []) or []:
        for model in getattr(program, "models", []) or []:
            for identity in getattr(model, "identities", []) or []:
                name = getattr(identity, "name", None)
                if not isinstance(name, str) or not name or name in seen:
                    continue

                seen.add(name)
                names.append(name)

    return names


async def async_setup_identity_store(hass: HomeAssistant) -> WyomingIdentityStore:
    """Set up the Wyoming identity store."""
    store = WyomingIdentityStore(hass)
    await store.async_setup()
    hass.data[DATA_IDENTITY_STORE] = store
    return store


@callback
def get_identity_store(hass: HomeAssistant) -> WyomingIdentityStore:
    """Return the Wyoming identity store."""
    return hass.data[DATA_IDENTITY_STORE]
