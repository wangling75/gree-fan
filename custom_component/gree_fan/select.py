"""Select 实体 - 水平摆风角度选择器（关、60°、80°、100°）."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COORDINATORS,
    DISPATCH_DEVICE_DISCOVERED,
    DISPATCHERS,
    DOMAIN,
    PROP_LR_ANGLE,
    PROP_ROTATE,
)
from .entity import GreeEntity

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    @callback
    def init_device(coordinator):
        if coordinator.profile.horizontal_angles:
            async_add_entities([GreeHorizontalSwingSelect(coordinator)])

    for coordinator in hass.data[DOMAIN][COORDINATORS]:
        init_device(coordinator)

    hass.data[DOMAIN][DISPATCHERS].append(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeHorizontalSwingSelect(GreeEntity, SelectEntity):
    """左右扫风角度选择器（关、60°、80°、100°）."""

    def __init__(self, coordinator) -> None:
        self._angle_values = dict(coordinator.profile.horizontal_angles)
        self._angle_options_reverse = {
            value: name for name, value in self._angle_values.items()
        }
        self._attr_options = ["关", *self._angle_values]
        super().__init__(coordinator, "左右扫风角度")
        _LOGGER.info(
            "[select] 左右扫风角度实体创建: name=%s, current=%s",
            self._attr_name,
            self.current_option,
        )

    async def async_added_to_hass(self) -> None:
        """注册实体到 hass.data，让 fan 可以联动更新。"""
        await super().async_added_to_hass()
        mac = self.coordinator.device.device_info.mac
        self.hass.data.setdefault(DOMAIN, {}).setdefault("selects", {})
        self.hass.data[DOMAIN]["selects"][mac] = self
        _LOGGER.info("[select] 已注册到 hass.data[DOMAIN]['selects'][%s]", mac)

    @property
    def current_option(self) -> str | None:
        """返回当前角度设置."""
        properties = self.coordinator.device._properties or {}
        rotating = properties.get(PROP_ROTATE)
        angle = properties.get(PROP_LR_ANGLE)
        option = (
            self._angle_options_reverse.get(angle, "关")
            if rotating == 1
            else "关"
        )
        _LOGGER.debug(
            "[select] current_option: Rotate=%s, LRAngle=%s, mapped=%s",
            rotating,
            angle,
            option,
        )
        return option

    async def async_select_option(self, option: str) -> None:
        """设置左右扫风角度."""
        if option not in self.options:
            raise ValueError(f"无效的角度: {option}")

        device = self.coordinator.device
        value = 0 if option == "关" else self._angle_values[option]

        if option == "关":
            _LOGGER.info("[select] 🌪️ 关闭左右扫风")
        else:
            _LOGGER.info(
                "[select] 🌪️ 开启左右扫风并设置角度: %s (value=%d)",
                option, value,
            )

        if device._properties is None:
            device._properties = {}

        # Rotate 控制摇头启停，LRAngle 控制摇头范围。两项须一起写入；
        # 向 SwingLfRig 写值只会影响空调，对风扇无效。
        updates = {PROP_ROTATE: 0} if option == "关" else {
            PROP_ROTATE: 1,
            PROP_LR_ANGLE: value,
        }
        for key, raw_value in updates.items():
            device._properties[key] = raw_value
            if key not in device._dirty:
                device._dirty.append(key)

        _LOGGER.info(
            "[select] 设置完成: _dirty=%s, Rotate=%s, LRAngle=%s",
            device._dirty,
            device._properties.get(PROP_ROTATE),
            device._properties.get(PROP_LR_ANGLE),
        )

        await self.coordinator.push_state_update()
        self.async_write_ha_state()

        # 联动更新风扇实体的摇头状态
        mac = device.device_info.mac
        fan_entity = self.hass.data.get(DOMAIN, {}).get("fans", {}).get(mac)
        if fan_entity:
            fan_entity.async_write_ha_state()
            _LOGGER.info("[select] ✅ 已联动更新风扇摇头状态")

        _LOGGER.info("[select] ✅ 左右扫风设置完成")
