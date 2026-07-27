"""Text 实体 - 倒计时关机（HH:MM 格式，最小 1 分钟，最大 8 小时）.

通过 hass.data[DOMAIN]["fans"] 查找同设备的风扇实体，调用其 async_set_timer 方法。
输入格式:
  - "HH:MM"  如 "02:30" → 2 小时 30 分
  - "H:MM"   如 "0:05"  → 5 分钟
  - "H:MM"   如 "1:30"  → 1 小时 30 分
  - "H"      如 "2"     → 2 小时
  - 0/空/00:00 → 取消定时
显示格式统一为 HH:MM，例如 "00:00"、"00:05"、"02:30"。
"""
from __future__ import annotations

import re

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COORDINATORS,
    DISPATCH_DEVICE_DISCOVERED,
    DISPATCHERS,
    DOMAIN,
    TIMER_MAX,
)
from .entity import GreeEntity

# 最大 8 小时 = 480 分钟
TIMER_MAX_MINUTES = TIMER_MAX * 60

# TextEntity 原生最长 255，2 位数字 + : + 2 位数字足够
_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")


def _parse_timer_input(value: str) -> int | None:
    """解析用户输入为分钟数，None 表示取消定时。

    支持格式:
      - "HH:MM"  如 "02:30" → 150 分钟
      - "H:MM"   如 "1:05"  → 65 分钟
      - "H"      纯整数小时 如 "2" → 120 分钟
      - "0.5"    小数小时 → 30 分钟
      - "0" / "" / "00:00" → None（取消）
    """
    if not value:
        return None
    s = value.strip()
    if s in ("0", "0.0", "00:00", "0:00"):
        return None

    # HH:MM 或 H:MM 格式
    if ":" in s:
        m = re.match(r"^(\d{1,2}):(\d{1,2})$", s)
        if not m:
            return -1  # 非法格式
        h, mn = int(m.group(1)), int(m.group(2))
        if mn >= 60:
            return -1
        total = h * 60 + mn
        if total == 0:
            return None
        return min(total, TIMER_MAX_MINUTES)

    # 纯数字：整数小时或小数小时
    try:
        f = float(s)
    except ValueError:
        return -1
    if f <= 0:
        return None
    total = round(f * 60)
    if total == 0:
        return None
    return min(total, TIMER_MAX_MINUTES)


def _format_minutes(total_minutes: int | float | None) -> str:
    """分钟数格式化为 HH:MM。"""
    if total_minutes is None or total_minutes <= 0:
        return "00:00"
    total = int(round(total_minutes))
    h, mn = divmod(total, 60)
    return f"{h:02d}:{mn:02d}"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置倒计时 Text 实体。"""

    @callback
    def init_device(coordinator):
        async_add_entities([GreeTimerText(coordinator)])

    for coordinator in hass.data[DOMAIN][COORDINATORS]:
        init_device(coordinator)

    hass.data[DOMAIN][DISPATCHERS].append(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeTimerText(GreeEntity, TextEntity):
    """倒计时关机实体（HH:MM 输入/显示）。"""

    _attr_icon = "mdi:timer-outline"
    _attr_mode = "text"
    _attr_native_max = 255  # TextEntity 必填，仅约束输入长度

    def __init__(self, coordinator) -> None:
        """初始化。"""
        super().__init__(coordinator, "倒计时关机")

    @property
    def native_value(self) -> str:
        """返回 HH:MM 格式剩余时间。"""
        fan = self._get_fan_entity()
        if fan is None:
            return "00:00"
        return _format_minutes(fan.timer_minutes)

    async def async_set_value(self, value: str) -> None:
        """解析用户输入为分钟数并下发到风扇实体。"""
        fan = self._get_fan_entity()
        if fan is None:
            return
        minutes = _parse_timer_input(value)
        if minutes == -1:
            _LOGGER.warning("[timer] 输入格式无效: %r", value)
            return
        await fan.async_set_timer_minutes(minutes)

    def _get_fan_entity(self):
        """通过 MAC 地址查找对应的风扇实体。"""
        mac = self.coordinator.device.device_info.mac
        return self.hass.data.get(DOMAIN, {}).get("fans", {}).get(mac)
