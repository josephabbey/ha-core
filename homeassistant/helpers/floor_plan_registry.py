"""Provides a common location system for integrations."""

# Floor Plans
# - There can be multiple floor plans (different levels)
# - Multiple floors can be on the same layer
# - Areas will have shapes
# - Devices can be placed and oriented
# - Integrations can provide overlays, either as scaled SVGs, or using primitives defined
# - Integrations should establish how to map between external floorplans (e.g. from robo vacuum app) and the internal coordinates

# Areas will hold their shape as a list of points within the
# area registry, they will inherit their layer from their floor

# Items are a way of manually placing things on the floor plan,
# this could be the location of the sofa, or a light which could
# be linked to its entity so that it can be controlled (similar to
# picture elements in lovelace).

# Example Integrations
# - mmWave Motion Sensor
#   - Default Overlay: Display Motion
#   - Integration Overlay: Display Ranges, Motion Zones
# - Robot Vacuum/Lawn mower
#   - Default Overlay: Location
#   - Integration Overlay: Path (history and plan), No go zones, cleaning zones, map according to the vacuum.
#   - Interaction Overlay: Draw path/area to clean

# device_tracker and vacuum will get new features with SUPPORTS_
# new selectors will be added for selecting a path, bounding box, zone (from the map gui)

# when setting up integrations/reconfiguring, that can use this, a gui will be provided that shows the floor plan
# and the world according to the integration, the user can resize/flip/rotate/stretch/move the world to align the
# two and the corresponding matrix will be saved.

from __future__ import annotations

from collections.abc import Iterable
import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.util.event_type import EventType
from homeassistant.util.hass_dict import HassKey

from .json import json_bytes, json_fragment
from .registry import BaseRegistry, BaseRegistryItems
from .singleton import singleton
from .storage import Store
from .typing import UNDEFINED, UndefinedType

if TYPE_CHECKING:
    # mypy cannot workout _cache Protocol with dataclasses
    from propcache.api import cached_property as under_cached_property
else:
    from propcache.api import under_cached_property

DATA_REGISTRY: HassKey[FloorPlanRegistry] = HassKey("floor_plan_registry")
EVENT_FLOOR_PLAN_REGISTRY_UPDATED: EventType[EventFloorPlanRegistryUpdatedData] = (
    EventType("floor_plan_registry_updated")
)
STORAGE_KEY = "core.floor_plan_registry"
STORAGE_VERSION_MAJOR = 0
STORAGE_VERSION_MINOR = 0


type Point = tuple[float, float]


class _FloorPlanStoreData(TypedDict):
    """Data type for individual floor plan. Used in FloorPlansRegistryStoreData."""

    level: int  # one per level, this is the id
    shape: list[Point] | None

    # This is an alternative to supplying the shape of the floor plan via shape
    background_image: str | None
    background_image_anchor: Point | None  # Relative to 0,0
    background_image_scale_x: float | None
    background_image_scale_y: float | None
    background_image_rotation: float | None
    created_at: str
    modified_at: str


class FloorPlansRegistryStoreData(TypedDict):
    """Store data type for FloorPlansRegistry."""

    floor_plans: list[_FloorPlanStoreData]


class EventFloorPlanRegistryUpdatedData(TypedDict):
    """EventFloorPlanRegistryUpdated data."""

    action: Literal["create", "remove", "update", "reorder"]
    level: int | None


@dataclass(frozen=True, kw_only=True, slots=True)
class FloorPlanEntry:
    """Floor Plan Registry Entry."""

    level: int
    shape: list[Point] | None
    background_image: str | None
    background_image_anchor: Point | None
    background_image_scale_x: float | None
    background_image_scale_y: float | None
    background_image_rotation: float | None
    created_at: datetime = field(default_factory=dt_util.utcnow)
    modified_at: datetime = field(default_factory=dt_util.utcnow)
    _cache: dict[str, Any] = field(default_factory=dict, compare=False, init=False)

    @under_cached_property
    def json_fragment(self) -> json_fragment:
        """Return a JSON representation of this AreaEntry."""
        return json_fragment(
            json_bytes(
                {
                    "level": self.level,
                    "shape": self.shape,
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


class FloorPlanRegistryStore(Store[FloorPlansRegistryStoreData]):
    """Store floor plan registry data."""


class FloorPlanRegistryItems(BaseRegistryItems[FloorPlanEntry]):
    """Class to hold floor plan registry items."""

    def _index_entry(self, key: str, entry: FloorPlanEntry) -> None:
        """Index an entry."""

    def _unindex_entry(
        self, key: str, replacement_entry: FloorPlanEntry | None = None
    ) -> None:
        """Unindex an entry."""


class FloorPlanRegistry(BaseRegistry[FloorPlansRegistryStoreData]):
    """A registry for floor plans."""

    floor_plans: FloorPlanRegistryItems
    _floor_plan_data: dict[int, FloorPlanEntry]

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the floor plan registry."""
        self.hass = hass
        self.floor_plans = FloorPlanRegistryItems()
        self._floor_plan_data = {}
        self._store = FloorPlanRegistryStore(
            hass,
            STORAGE_VERSION_MAJOR,
            STORAGE_KEY,
            atomic_writes=True,
            minor_version=STORAGE_VERSION_MINOR,
        )

    @callback
    def async_get_floor_plan(self, level: int) -> FloorPlanEntry | None:
        """Get a floor plan by its ID."""
        return self._floor_plan_data.get(level)

    @callback
    def async_list_floor_plans(self) -> Iterable[FloorPlanEntry]:
        """Get all floor plans."""
        return self.floor_plans.values()

    @callback
    def async_get_or_create(self, level: int) -> FloorPlanEntry:
        """Get or create a floor plan."""
        if floor_plan := self.async_get_floor_plan(level):
            return floor_plan
        return self.async_create(level)

    @callback
    def async_create(
        self,
        level: int,
        *,
        shape: list[Point] | None = None,
        background_image: str | None = None,
        background_image_anchor: Point | None = None,
        background_image_scale_x: float | None = None,
        background_image_scale_y: float | None = None,
        background_image_rotation: float | None = None,
    ) -> FloorPlanEntry:
        """Create a floor plan."""

        self.hass.verify_event_loop_thread("floor_plan_registry.async_create")

        if floor_plan := self.async_get_floor_plan(level):
            raise ValueError(f"Floor plan for level {level} already exists")

        floor_plan = FloorPlanEntry(
            level=level,
            shape=shape,
            background_image=background_image,
            background_image_anchor=background_image_anchor,
            background_image_scale_x=background_image_scale_x,
            background_image_scale_y=background_image_scale_y,
            background_image_rotation=background_image_rotation,
        )
        self._floor_plan_data[level] = floor_plan
        self.floor_plans[str(level)] = floor_plan
        return floor_plan

    @callback
    def async_delete(self, level: int) -> None:
        """Delete a floor plan."""
        self.hass.verify_event_loop_thread("floor_plan_registry.async_delete")
        del self._floor_plan_data[level]
        del self.floor_plans[str(level)]

        self.hass.bus.async_fire_internal(
            EVENT_FLOOR_PLAN_REGISTRY_UPDATED,
            EventFloorPlanRegistryUpdatedData(action="remove", level=level),
        )

    @callback
    def async_update(
        self,
        level: int,
        *,
        shape: list[Point] | None = None,
        background_image: str | None = None,
        background_image_anchor: Point | None = None,
        background_image_scale_x: float | None = None,
        background_image_scale_y: float | None = None,
        background_image_rotation: float | None = None,
    ) -> FloorPlanEntry:
        """Update a floor plan."""
        updated = self._async_update(
            level,
            shape=shape,
            background_image=background_image,
            background_image_anchor=background_image_anchor,
            background_image_scale_x=background_image_scale_x,
            background_image_scale_y=background_image_scale_y,
            background_image_rotation=background_image_rotation,
        )
        self.hass.bus.async_fire(
            EVENT_FLOOR_PLAN_REGISTRY_UPDATED,
            EventFloorPlanRegistryUpdatedData(action="update", level=level),
        )
        return updated

    @callback
    def _async_update(
        self,
        level: int,
        *,
        shape: list[Point] | None | UndefinedType = UNDEFINED,
        background_image: str | None | UndefinedType = UNDEFINED,
        background_image_anchor: Point | None | UndefinedType = UNDEFINED,
        background_image_scale_x: float | None | UndefinedType = UNDEFINED,
        background_image_scale_y: float | None | UndefinedType = UNDEFINED,
        background_image_rotation: float | None | UndefinedType = UNDEFINED,
    ) -> FloorPlanEntry:
        """Update a floor plan entry."""

        # Changing the level will have to be handled separately

        old = self.floor_plans[str(level)]

        new_values: dict[str, Any] = {
            attr_name: value
            for attr_name, value in (
                ("shape", shape),
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

        self.hass.verify_event_loop_thread("floor_plan_registry.async_update")
        new = self.floor_plans[str(level)] = dataclasses.replace(old, **new_values)

        self.async_schedule_save()
        return new

    async def _async_load(self) -> None:
        """Load the floor plan registry."""

        data = await self._store.async_load()

        floor_plans = FloorPlanRegistryItems()

        if data is not None:
            for floor_plan in data["floor_plans"]:
                assert floor_plan["level"] is not None
                floor_plans[str(floor_plan["level"])] = FloorPlanEntry(
                    level=floor_plan["level"],
                    shape=floor_plan["shape"],
                    background_image=floor_plan["background_image"],
                    background_image_anchor=floor_plan["background_image_anchor"],
                    background_image_scale_x=floor_plan["background_image_scale_x"],
                    background_image_scale_y=floor_plan["background_image_scale_y"],
                    background_image_rotation=floor_plan["background_image_rotation"],
                    created_at=datetime.fromisoformat(floor_plan["created_at"]),
                    modified_at=datetime.fromisoformat(floor_plan["modified_at"]),
                )

        self.floor_plans = floor_plans
        self._floor_plan_data = {entry.level: entry for entry in floor_plans.values()}

    @callback
    def _data_to_save(self) -> FloorPlansRegistryStoreData:
        """Return data of floor plan registry to store in a file."""
        return cast(
            FloorPlansRegistryStoreData,
            {
                "floor_plans": [
                    {
                        "level": entry.level,
                        "shape": entry.shape,
                        "background_image": entry.background_image,
                        "background_image_anchor": list(entry.background_image_anchor)
                        if entry.background_image_anchor
                        else None,
                        "background_image_scale_x": entry.background_image_scale_x,
                        "background_image_scale_y": entry.background_image_scale_y,
                        "background_image_rotation": entry.background_image_rotation,
                        "created_at": entry.created_at.isoformat(),
                        "modified_at": entry.modified_at.isoformat(),
                    }
                    for entry in self.floor_plans.values()
                ]
            },
        )


@callback
@singleton(DATA_REGISTRY)
def async_get(hass: HomeAssistant) -> FloorPlanRegistry:
    """Get floor plan registry."""
    return FloorPlanRegistry(hass)


async def async_load(hass: HomeAssistant, *, load_empty: bool = False) -> None:
    """Load floor plan registry."""
    assert DATA_REGISTRY not in hass.data
    await async_get(hass).async_load(load_empty=load_empty)
