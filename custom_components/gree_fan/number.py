"""Number 实体 - 定时关机（0-8小时）.

通过 hass.data[DOMAIN]["fans"] 查找同设备的风扇实体，
调用其 async_set_timer 方法。"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COORDINATORS,
    DISPATCH_DEVICE_DISCOVERED,
    DISPATCHERS,
    DOMAIN,
    TIMER_MIN,
    TIMER_MAX,
    TIMER_STEP,
)
from .entity import GreeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置定时 Number 实体。"""

    @callback
    def init_device(coordinator):
        async_add_entities([GreeTimerNumber(coordinator)])

    for coordinator in hass.data[DOMAIN][COORDINATORS]:
        init_device(coordinator)

    hass.data[DOMAIN][DISPATCHERS].append(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeTimerNumber(GreeEntity, NumberEntity):
    """定时关机（0-8小时）。"""

    _attr_native_min_value = float(TIMER_MIN)
    _attr_native_max_value = float(TIMER_MAX)
    _attr_native_step = float(TIMER_STEP)
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator) -> None:
        """初始化。"""
        super().__init__(coordinator, "定时关机")

    @property
    def native_value(self) -> float:
        """返回当前定时小时数。"""
        fan = self._get_fan_entity()
        return float(fan.timer_hours) if fan else 0.0

    async def async_set_native_value(self, value: float) -> None:
        """设置定时小时数。"""
        fan = self._get_fan_entity()
        if fan is not None:
            await fan.async_set_timer(int(value))

    def _get_fan_entity(self):
        """通过 MAC 地址查找对应的风扇实体。"""
        mac = self.coordinator.device.device_info.mac
        return self.hass.data.get(DOMAIN, {}).get("fans", {}).get(mac)
