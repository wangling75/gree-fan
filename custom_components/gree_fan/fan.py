"""格力风扇 - 完整功能版（开关 + 风速 + 摆风）."""
from __future__ import annotations

import asyncio
import logging
import typing as t

from greeclimate.device import Props

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .bridge import DeviceDataUpdateCoordinator
from .const import (
    COORDINATORS, DISPATCH_DEVICE_DISCOVERED, DISPATCHERS,
    DOMAIN, SPEED_COUNT, SPEED_RANGE,
    TIMER_MAX, TIMER_MIN,
)

_LOGGER = logging.getLogger(__name__)

MODE_NORMAL, MODE_SLEEP, MODE_AUTO = 0, 2, 6

FAN_PRESET_MODES = {
    "普通风": MODE_NORMAL,
    "睡眠风": MODE_SLEEP,
    "快循环": MODE_AUTO,
}
FAN_PRESET_MODES_REVERSE = {v: k for k, v in FAN_PRESET_MODES.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    @callback
    def init_device(coordinator):
        async_add_entities([GreeFanEntity(coordinator)])

    for coordinator in hass.data[DOMAIN][COORDINATORS]:
        init_device(coordinator)

    hass.data[DOMAIN][DISPATCHERS].append(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeFanEntity(CoordinatorEntity[DeviceDataUpdateCoordinator], FanEntity):
    """格力风扇 — 开关 + 风速（8档）+ 摆风."""

    _attr_has_entity_name = False
    _attr_name: str | None = None
    _attr_speed_count = SPEED_COUNT

    # 关键：必须显式声明 TURN_ON/TURN_OFF/SET_SPEED
    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
    )

    _timer_task: asyncio.Task | None = None
    _timer_hours: int = 0

    def __init__(self, coordinator: DeviceDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = coordinator.device.device_info.name
        mac = coordinator.device.device_info.mac
        self._attr_unique_id = mac
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, mac)},
            identifiers={(DOMAIN, mac)},
            manufacturer="Gree",
            name=self._attr_name,
        )
        _LOGGER.info(
            "[fan] ✅ Entity: name=%s, mac=%s, key=%s, ip=%s, features=%s",
            self._attr_name, mac,
            coordinator.device.device_key,
            coordinator.device.device_info.ip,
            self._attr_supported_features,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        mac = self.coordinator.device.device_info.mac
        self.hass.data[DOMAIN].setdefault("fans", {})
        self.hass.data[DOMAIN]["fans"][mac] = self
        _LOGGER.info(
            "[fan] added: power=%s, fan_speed=%s, SwingLfRig=%s, _properties=%s",
            self.coordinator.device.power,
            self.coordinator.device.fan_speed,
            self.coordinator.device.get_property(Props.SWING_HORIZ),
            self.coordinator.device._properties,
        )

    # ── 开关 ──
    @property
    def is_on(self) -> bool:
        return self.coordinator.device.power is True

    async def async_turn_on(
        self,
        percentage: t.Optional[int] = None,
        preset_mode: t.Optional[str] = None,
        **kwargs: t.Any,
    ) -> None:
        _LOGGER.info(
            "[fan] 🟢 turn_on: percentage=%s preset=%s",
            percentage, preset_mode,
        )
        device = self.coordinator.device

        if preset_mode:
            await self.async_set_preset_mode(preset_mode)
            return

        if percentage is None:
            device.power = True
            if device.mode is None:
                device.mode = MODE_NORMAL
        else:
            device.power = True
            if device.mode is None:
                device.mode = MODE_NORMAL
            speed = round(percentage_to_ranged_value(SPEED_RANGE, percentage))
            device.fan_speed = speed
            self._attr_percentage = ranged_value_to_percentage(SPEED_RANGE, speed)

        _LOGGER.info(
            "[fan] turn_on: _dirty=%s key=%s ip=%s",
            device._dirty, device.device_key, device.device_info.ip,
        )
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: t.Any) -> None:
        _LOGGER.info("[fan] 🔴 turn_off: _dirty=%s", self.coordinator.device._dirty)
        self.coordinator.device.power = False
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    # ── 风速 ──
    async def async_set_percentage(self, percentage: int) -> None:
        # 0% → 关闭风扇，与开关实体状态同步
        if percentage == 0:
            await self.async_turn_off()
            return

        device = self.coordinator.device

        if not device.power:
            device.power = True
            if device.mode is None:
                device.mode = MODE_NORMAL

        speed = round(percentage_to_ranged_value(SPEED_RANGE, percentage))
        device.fan_speed = speed
        self._attr_percentage = ranged_value_to_percentage(SPEED_RANGE, speed)

        _LOGGER.info(
            "[fan] 🎚️ set_percentage: %d%% → speed=%d _dirty=%s",
            percentage, speed, device._dirty,
        )
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    # ── 模式 ──
    @property
    def preset_mode(self) -> t.Optional[str]:
        if not self.coordinator.device.power:
            return None
        return FAN_PRESET_MODES_REVERSE.get(self.coordinator.device.mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self.preset_modes:
            raise ValueError(f"无效模式: {preset_mode}")
        device = self.coordinator.device
        device.power = True
        device.mode = FAN_PRESET_MODES[preset_mode]
        _LOGGER.info("[fan] 🎯 set_preset_mode: %s (mode=%d)", preset_mode, FAN_PRESET_MODES[preset_mode])
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    # ── 定时 ──
    @property
    def timer_hours(self) -> int:
        return self._timer_hours

    async def async_set_timer(self, hours: int) -> None:
        hours = max(TIMER_MIN, min(TIMER_MAX, hours))
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None
        self._timer_hours = hours
        if hours > 0:
            self._timer_task = asyncio.create_task(self._timer_countdown(hours))
        self.async_write_ha_state()

    async def _timer_countdown(self, hours: int) -> None:
        try:
            await asyncio.sleep(hours * 3600)
            await self.async_turn_off()
            self._timer_hours = 0
            self.async_write_ha_state()
        except asyncio.CancelledError:
            pass
