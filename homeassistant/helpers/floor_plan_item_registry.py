"""Provide a dedicated registry for items placed on floor plans."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.util.event_type import EventType
from homeassistant.util.hass_dict import HassKey

from .floor_plan_registry import Point
from .json import json_bytes, json_fragment
from .registry import BaseRegistry, BaseRegistryItems, RegistryIndexType
from .singleton import singleton
from .storage import Store
from .typing import UNDEFINED, UndefinedType

if TYPE_CHECKING:
    # mypy cannot workout _cache Protocol with dataclasses
    from propcache.api import cached_property as under_cached_property
else:
    from propcache.api import under_cached_property


DATA_REGISTRY: HassKey[FloorPlanItemRegistry] = HassKey("floor_plan_item_registry")
EVENT_FLOOR_PLAN_ITEM_REGISTRY_UPDATED: EventType[
    EventFloorPlanItemRegistryUpdatedData
] = EventType("floor_plan_item_registry_updated")
STORAGE_KEY = "core.floor_plan_item_registry"
STORAGE_VERSION_MAJOR = 1
STORAGE_VERSION_MINOR = 0


class _ItemData(TypedDict):
    """Shared item fields for floor plan item payloads."""

    entity_id: str | None
    icon: str | None
    color: str | None
    shape: list[Point] | None
    location: Point
    background_image: str | None
    background_image_anchor: Point | None
    background_image_scale_x: float | None
    background_image_scale_y: float | None
    background_image_rotation: float | None


class Item(_ItemData):
    """Data type for an item in a floor plan."""

    item_id: str


class _FloorPlanItemStoreData(_ItemData):
    """Data type for an individual floor plan item."""

    item_id: str
    level: int
    created_at: str
    modified_at: str


class FloorPlanItemRegistryStoreData(TypedDict):
    """Store data type for FloorPlanItemRegistry."""

    floor_plan_items: list[_FloorPlanItemStoreData]


class EventFloorPlanItemRegistryUpdatedData(TypedDict):
    """EventFloorPlanItemRegistryUpdated data."""

    action: Literal["create", "remove", "update", "reorder"]
    item_id: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class FloorPlanItemEntry:
    """Floor plan item registry entry."""

    item_id: str
    level: int

    # Optionally link to an entity, to allow interactions and updates.
    entity_id: str | None

    # Can be templates; if an entity is linked, the icon will be used.
    icon: str | None
    color: str | None

    shape: list[Point] | None
    location: Point

    # This is an alternative to supplying the shape/icon of the item
    # If shape is also applied, it will be used as the collision box for clicking
    background_image: str | None
    background_image_anchor: Point | None  # Relative to the location
    background_image_scale_x: float | None
    background_image_scale_y: float | None
    background_image_rotation: float | None

    created_at: datetime = field(default_factory=dt_util.utcnow)
    modified_at: datetime = field(default_factory=dt_util.utcnow)
    _cache: dict[str, Any] = field(default_factory=dict, compare=False, init=False)

    @under_cached_property
    def json_fragment(self) -> json_fragment:
        """Return a JSON representation of this FloorPlanItemEntry."""
        return json_fragment(
            json_bytes(
                {
                    "item_id": self.item_id,
                    "level": self.level,
                    "entity_id": self.entity_id,
                    "icon": self.icon,
                    "color": self.color,
                    "shape": self.shape,
                    "location": self.location,
                    "background_image": self.background_image,
                    "background_image_anchor": self.background_image_anchor,
                    "background_image_scale_x": self.background_image_scale_x,
                    "background_image_scale_y": self.background_image_scale_y,
                    "background_image_rotation": self.background_image_rotation,
                    "created_at": self.created_at.timestamp(),
                    "modified_at": self.modified_at.timestamp(),
                }
            )
        )


class FloorPlanItemRegistryStore(Store[FloorPlanItemRegistryStoreData]):
    """Store floor plan item registry data."""


class FloorPlanItemRegistryItems(BaseRegistryItems[FloorPlanItemEntry]):
    """Class to hold floor plan item registry items."""

    def __init__(self) -> None:
        """Initialize the floor plan item registry items."""
        super().__init__()
        self._levels_index: RegistryIndexType = defaultdict(dict)

    def _index_entry(self, key: str, entry: FloorPlanItemEntry) -> None:
        """Index an entry."""
        self._levels_index[str(entry.level)][key] = True

    def _unindex_entry(
        self, key: str, replacement_entry: FloorPlanItemEntry | None = None
    ) -> None:
        """Unindex an entry."""
        entry = self.data[key]
        self._unindex_entry_value(key, str(entry.level), self._levels_index)

    def get_items_for_level(self, level: int) -> list[FloorPlanItemEntry]:
        """Get items for level."""
        data = self.data
        return [data[key] for key in self._levels_index.get(str(level), ())]


class FloorPlanItemRegistry(BaseRegistry[FloorPlanItemRegistryStoreData]):
    """A flat registry for floor plan items."""

    floor_plan_items: FloorPlanItemRegistryItems
    _floor_plan_item_data: dict[str, FloorPlanItemEntry]

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the floor plan item registry."""
        self.hass = hass
        self.floor_plan_items = FloorPlanItemRegistryItems()
        self._floor_plan_item_data = {}
        self._store = FloorPlanItemRegistryStore(
            hass,
            STORAGE_VERSION_MAJOR,
            STORAGE_KEY,
            atomic_writes=True,
            minor_version=STORAGE_VERSION_MINOR,
        )

    @callback
    def async_get_floor_plan_item(self, item_id: str) -> FloorPlanItemEntry | None:
        """Get a floor plan item by ID."""
        return self._floor_plan_item_data.get(item_id)

    @callback
    def async_get_floor_plan_items_for_level(
        self, level: int
    ) -> list[FloorPlanItemEntry]:
        """Get floor plan items for a level."""
        return self.floor_plan_items.get_items_for_level(level)

    @callback
    def async_list_floor_plan_items(self) -> Iterable[FloorPlanItemEntry]:
        """Get all floor plan item entries."""
        return self.floor_plan_items.values()

    @callback
    def async_create(
        self,
        item_id: str,
        *,
        level: int,
        entity_id: str | None = None,
        icon: str | None = None,
        color: str | None = None,
        shape: list[Point] | None = None,
        location: Point,
        background_image: str | None = None,
        background_image_anchor: Point | None = None,
        background_image_scale_x: float | None = None,
        background_image_scale_y: float | None = None,
        background_image_rotation: float | None = None,
    ) -> FloorPlanItemEntry:
        """Create a floor plan item."""
        self.hass.verify_event_loop_thread("floor_plan_item_registry.async_create")

        if self.async_get_floor_plan_item(item_id):
            raise ValueError(f"Floor plan item with id {item_id} already exists")

        entry = FloorPlanItemEntry(
            item_id=item_id,
            level=level,
            entity_id=entity_id,
            icon=icon,
            color=color,
            shape=shape,
            location=location,
            background_image=background_image,
            background_image_anchor=background_image_anchor,
            background_image_scale_x=background_image_scale_x,
            background_image_scale_y=background_image_scale_y,
            background_image_rotation=background_image_rotation,
        )
        self.floor_plan_items[item_id] = entry
        self._floor_plan_item_data[item_id] = entry
        self.async_schedule_save()

        self.hass.bus.async_fire_internal(
            EVENT_FLOOR_PLAN_ITEM_REGISTRY_UPDATED,
            EventFloorPlanItemRegistryUpdatedData(action="create", item_id=item_id),
        )

        return entry

    @callback
    def async_delete(self, item_id: str) -> None:
        """Delete a floor plan item."""
        self.hass.verify_event_loop_thread("floor_plan_item_registry.async_delete")
        del self._floor_plan_item_data[item_id]
        del self.floor_plan_items[item_id]
        self.async_schedule_save()

        self.hass.bus.async_fire_internal(
            EVENT_FLOOR_PLAN_ITEM_REGISTRY_UPDATED,
            EventFloorPlanItemRegistryUpdatedData(action="remove", item_id=item_id),
        )

    @callback
    def async_update(
        self,
        item_id: str,
        *,
        level: int | UndefinedType = UNDEFINED,
        entity_id: str | None | UndefinedType = UNDEFINED,
        icon: str | None | UndefinedType = UNDEFINED,
        color: str | None | UndefinedType = UNDEFINED,
        shape: list[Point] | None | UndefinedType = UNDEFINED,
        location: Point | UndefinedType = UNDEFINED,
        background_image: str | None | UndefinedType = UNDEFINED,
        background_image_anchor: Point | None | UndefinedType = UNDEFINED,
        background_image_scale_x: float | None | UndefinedType = UNDEFINED,
        background_image_scale_y: float | None | UndefinedType = UNDEFINED,
        background_image_rotation: float | None | UndefinedType = UNDEFINED,
    ) -> FloorPlanItemEntry:
        """Update a floor plan item."""
        updated = self._async_update(
            item_id,
            level=level,
            entity_id=entity_id,
            icon=icon,
            color=color,
            shape=shape,
            location=location,
            background_image=background_image,
            background_image_anchor=background_image_anchor,
            background_image_scale_x=background_image_scale_x,
            background_image_scale_y=background_image_scale_y,
            background_image_rotation=background_image_rotation,
        )
        self.hass.bus.async_fire(
            EVENT_FLOOR_PLAN_ITEM_REGISTRY_UPDATED,
            EventFloorPlanItemRegistryUpdatedData(action="update", item_id=item_id),
        )
        return updated

    @callback
    def _async_update(
        self,
        item_id: str,
        *,
        level: int | UndefinedType = UNDEFINED,
        entity_id: str | None | UndefinedType = UNDEFINED,
        icon: str | None | UndefinedType = UNDEFINED,
        color: str | None | UndefinedType = UNDEFINED,
        shape: list[Point] | None | UndefinedType = UNDEFINED,
        location: Point | UndefinedType = UNDEFINED,
        background_image: str | None | UndefinedType = UNDEFINED,
        background_image_anchor: Point | None | UndefinedType = UNDEFINED,
        background_image_scale_x: float | None | UndefinedType = UNDEFINED,
        background_image_scale_y: float | None | UndefinedType = UNDEFINED,
        background_image_rotation: float | None | UndefinedType = UNDEFINED,
    ) -> FloorPlanItemEntry:
        """Update a floor plan item entry."""
        old = self.floor_plan_items[item_id]

        new_values: dict[str, Any] = {
            attr_name: value
            for attr_name, value in (
                ("level", level),
                ("entity_id", entity_id),
                ("icon", icon),
                ("color", color),
                ("shape", shape),
                ("location", location),
                ("background_image", background_image),
                ("background_image_anchor", background_image_anchor),
                ("background_image_scale_x", background_image_scale_x),
                ("background_image_scale_y", background_image_scale_y),
                ("background_image_rotation", background_image_rotation),
            )
            if value is not UNDEFINED and value != getattr(old, attr_name)
        }

        if not new_values:
            return old

        new_values["modified_at"] = dt_util.utcnow()

        self.hass.verify_event_loop_thread("floor_plan_item_registry.async_update")
        new = self.floor_plan_items[item_id] = dataclasses.replace(old, **new_values)
        self._floor_plan_item_data[item_id] = new

        self.async_schedule_save()
        return new

    async def _async_load(self) -> None:
        """Load the floor plan item registry."""
        data = await self._store.async_load()

        floor_plan_items = FloorPlanItemRegistryItems()

        if data is not None:
            for floor_plan_item in data["floor_plan_items"]:
                item_id = floor_plan_item["item_id"]
                floor_plan_items[item_id] = FloorPlanItemEntry(
                    item_id=item_id,
                    level=floor_plan_item["level"],
                    entity_id=floor_plan_item["entity_id"],
                    icon=floor_plan_item["icon"],
                    color=floor_plan_item["color"],
                    shape=floor_plan_item["shape"],
                    location=floor_plan_item["location"],
                    background_image=floor_plan_item["background_image"],
                    background_image_anchor=floor_plan_item["background_image_anchor"],
                    background_image_scale_x=floor_plan_item[
                        "background_image_scale_x"
                    ],
                    background_image_scale_y=floor_plan_item[
                        "background_image_scale_y"
                    ],
                    background_image_rotation=floor_plan_item[
                        "background_image_rotation"
                    ],
                    created_at=datetime.fromisoformat(floor_plan_item["created_at"]),
                    modified_at=datetime.fromisoformat(floor_plan_item["modified_at"]),
                )

        self.floor_plan_items = floor_plan_items
        self._floor_plan_item_data = floor_plan_items.data

    @callback
    def _data_to_save(self) -> FloorPlanItemRegistryStoreData:
        """Return data of floor plan item registry to store in a file."""
        return {
            "floor_plan_items": [
                {
                    "item_id": entry.item_id,
                    "level": entry.level,
                    "entity_id": entry.entity_id,
                    "icon": entry.icon,
                    "color": entry.color,
                    "shape": entry.shape,
                    "location": entry.location,
                    "background_image": entry.background_image,
                    "background_image_anchor": entry.background_image_anchor,
                    "background_image_scale_x": entry.background_image_scale_x,
                    "background_image_scale_y": entry.background_image_scale_y,
                    "background_image_rotation": entry.background_image_rotation,
                    "created_at": entry.created_at.isoformat(),
                    "modified_at": entry.modified_at.isoformat(),
                }
                for entry in self.floor_plan_items.values()
            ]
        }


@callback
@singleton(DATA_REGISTRY)
def async_get(hass: HomeAssistant) -> FloorPlanItemRegistry:
    """Get floor plan item registry."""
    return FloorPlanItemRegistry(hass)


async def async_load(hass: HomeAssistant, *, load_empty: bool = False) -> None:
    """Load floor plan item registry."""
    assert DATA_REGISTRY not in hass.data
    await async_get(hass).async_load(load_empty=load_empty)
