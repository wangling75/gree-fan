"""Switch 实体 - 垂直摆风开关 + 原有格力空调附件开关."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from greeclimate.device import Device
from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COORDINATORS,
    DISPATCH_DEVICE_DISCOVERED,
    DISPATCHERS,
    DOMAIN,
    PROP_SW_UP_DOWN,
    PROP_UP_DOWN_ANGLE,
    VERTICAL_SWING_OFF,
    VERTICAL_SWING_ON,
)
from .entity import GreeEntity
from .profiles import FanProfile

_LOGGER = logging.getLogger(__name__)


@dataclass
class GreeRequiredKeysMixin:
    """Mixin for required keys."""

    get_value_fn: Callable[[Device], bool]
    set_value_fn: Callable[[Device, bool, FanProfile], None]


@dataclass
class GreeSwitchEntityDescription(SwitchEntityDescription, GreeRequiredKeysMixin):
    """Describes Gree switch entity."""

    name: str = ""


# ---- 附件开关（原空调功能，在风扇上不一定都支持） ----

def _set_light(device: Device, value: bool) -> None:
    device.light = value

def _set_quiet(device: Device, value: bool) -> None:
    device.quiet = value

def _set_fresh_air(device: Device, value: bool) -> None:
    device.fresh_air = value

def _set_xfan(device: Device, value: bool) -> None:
    device.xfan = value

def _set_anion(device: Device, value: bool) -> None:
    device.anion = value

def _mark_property_dirty(device: Device, prop: str, value: int) -> None:
    """Set a raw property and ensure it is included in the next command."""
    if device._properties is None:
        device._properties = {}

    device._properties[prop] = value
    # Re-send even when the cached value matches the requested value.
    if prop not in device._dirty:
        device._dirty.append(prop)


def _set_vertical_swing(
    device: Device,
    value: bool,
    profile: FanProfile,
) -> None:
    """Control vertical swing and initialize a required model-specific angle."""
    raw_value = VERTICAL_SWING_ON if value else VERTICAL_SWING_OFF
    _mark_property_dirty(device, PROP_SW_UP_DOWN, raw_value)

    angle = profile.vertical_swing_angle
    if value and angle is not None and profile.supports(PROP_UP_DOWN_ANGLE):
        # MID 828209 ignores a bare SwUpDn=1 until UpDnAngle has been set.
        _mark_property_dirty(device, PROP_UP_DOWN_ANGLE, angle)
        _LOGGER.info(
            "设置上下摆风: SwUpDn=%d, UpDnAngle=%d",
            raw_value,
            angle,
        )
        return

    _LOGGER.info("设置上下摆风: SwUpDn=%d", raw_value)


GREE_SWITCHES: tuple[GreeSwitchEntityDescription, ...] = (
    # ---- 垂直摆风（风扇核心功能） ----
    GreeSwitchEntityDescription(
        name="上下摆风",
        key="vertical_swing",
        icon="mdi:swap-vertical",
        get_value_fn=lambda d: (
            (d._properties or {}).get(PROP_SW_UP_DOWN) == VERTICAL_SWING_ON
        ),
        set_value_fn=_set_vertical_swing,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Gree switch entities."""

    @callback
    def init_device(coordinator):
        """Register the device."""
        if not coordinator.supports(PROP_SW_UP_DOWN):
            return
        async_add_entities(
            GreeSwitch(coordinator=coordinator, description=description)
            for description in GREE_SWITCHES
        )

    for coordinator in hass.data[DOMAIN][COORDINATORS]:
        init_device(coordinator)

    hass.data[DOMAIN][DISPATCHERS].append(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeSwitch(GreeEntity, SwitchEntity):
    """Generic Gree switch entity."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    entity_description: GreeSwitchEntityDescription

    def __init__(self, coordinator, description: GreeSwitchEntityDescription) -> None:
        """Initialize the Gree device."""
        self.entity_description = description
        super().__init__(coordinator, description.name)

    @property
    def is_on(self) -> bool:
        """Return if the state is turned on."""
        return self.entity_description.get_value_fn(self.coordinator.device)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self.entity_description.set_value_fn(
            self.coordinator.device,
            True,
            self.coordinator.profile,
        )
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self.entity_description.set_value_fn(
            self.coordinator.device,
            False,
            self.coordinator.profile,
        )
        await self.coordinator.push_state_update()
        self.async_write_ha_state()
