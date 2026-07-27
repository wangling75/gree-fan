"""Select 实体 - 水平摆风角度选择器（关、60°、80°、100°）."""
from __future__ import annotations

import logging

from greeclimate.device import Props
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import GreeEntity
from .const import COORDINATORS, DISPATCH_DEVICE_DISCOVERED, DISPATCHERS, DOMAIN

_LOGGER = logging.getLogger(__name__)

# 格力风扇 XFan 左右扫风角度映射（关 + 60°、80°、100°）
HORIZONTAL_SWING_OPTIONS = {
    "关":   0,  # 关闭摆风
    "60°":  2,  # 中角度
    "80°":  3,  # 大角度  
    "100°": 4,  # 更大角度
}
HORIZONTAL_SWING_OPTIONS_REVERSE = {v: k for k, v in HORIZONTAL_SWING_OPTIONS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    @callback
    def init_device(coordinator):
        async_add_entities([GreeHorizontalSwingSelect(coordinator)])

    for coordinator in hass.data[DOMAIN][COORDINATORS]:
        init_device(coordinator)

    hass.data[DOMAIN][DISPATCHERS].append(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeHorizontalSwingSelect(GreeEntity, SelectEntity):
    """左右扫风角度选择器（关、60°、80°、100°）."""

    _attr_options = list(HORIZONTAL_SWING_OPTIONS.keys())

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "左右扫风角度")
        _LOGGER.info(
            "[select] 左右扫风角度实体创建: name=%s, current=%s",
            self._attr_name,
            self.current_option,
        )

    @property
    def current_option(self) -> str | None:
        """返回当前角度设置."""
        val = self.coordinator.device.get_property(Props.SWING_HORIZ)
        option = HORIZONTAL_SWING_OPTIONS_REVERSE.get(val, "关")
        _LOGGER.debug("[select] current_option: raw=%s, mapped=%s", val, option)
        return option

    async def async_select_option(self, option: str) -> None:
        """设置左右扫风角度."""
        if option not in self.options:
            raise ValueError(f"无效的角度: {option}")

        device = self.coordinator.device
        swing_key = Props.SWING_HORIZ.value  # "SwingLfRig"
        value = HORIZONTAL_SWING_OPTIONS[option]

        if option == "关":
            _LOGGER.info("[select] 🌪️ 关闭左右扫风")
        else:
            _LOGGER.info(
                "[select] 🌪️ 开启左右扫风并设置角度: %s (value=%d)",
                option, value,
            )

        device._dirty.append(swing_key)
        device._properties[swing_key] = value

        _LOGGER.info(
            "[select] 设置完成: _dirty=%s, SwingLfRig=%s",
            device._dirty,
            device._properties.get(swing_key),
        )

        await self.coordinator.push_state_update()
        self.async_write_ha_state()
        _LOGGER.info("[select] ✅ 左右扫风设置完成")
