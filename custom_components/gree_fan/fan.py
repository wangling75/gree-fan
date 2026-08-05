"""格力风扇 - 完整功能版（开关 + 风速 + 摆风）."""
from __future__ import annotations

import asyncio
import logging
import typing as t
from datetime import datetime, timezone

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
    DOMAIN, HORIZONTAL_SWING_OPTIONS, SPEED_COUNT, SPEED_RANGE,
    PROP_LR_ANGLE, PROP_ROTATE, TIMER_MAX, TIMER_MIN,
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
    _attr_preset_modes = list(FAN_PRESET_MODES.keys())

    # 关键：必须显式声明 TURN_ON/TURN_OFF/SET_SPEED + PRESET_MODE + OSCILLATE
    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.OSCILLATE
    )

    _timer_handle: asyncio.TimerHandle | None = None
    _timer_end_time: float | None = None

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
            "[fan] ✅ Entity: name=%s, mac=%s, ip=%s, features=%s",
            self._attr_name, mac,
            coordinator.device.device_info.ip,
            self._attr_supported_features,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        mac = self.coordinator.device.device_info.mac
        self.hass.data[DOMAIN].setdefault("fans", {})
        self.hass.data[DOMAIN]["fans"][mac] = self

        # HA 重启后，恢复持久化的倒计时
        state = self.hass.states.get(self.entity_id)
        if state and state.attributes:
            raw = state.attributes.get("timer_end_time")
            if raw:
                try:
                    # 从 UTC 时间戳恢复
                    timer_end_timestamp = float(raw)
                    now_timestamp = datetime.now(timezone.utc).timestamp()
                    remaining = timer_end_timestamp - now_timestamp
                    
                    _LOGGER.info(
                        "[fan] ⏱️ 恢复倒计时，剩余 %.1f 秒（结束时间: %s）",
                        remaining,
                        datetime.fromtimestamp(timer_end_timestamp, tz=timezone.utc).strftime("%H:%M:%S UTC"),
                    )
                    
                    if remaining > 0:
                        self._timer_end_time = timer_end_timestamp
                        self._schedule_timer_callback(remaining)
                    else:
                        _LOGGER.info("[fan] ⏱️ 倒计时已过期，执行关闭")
                        await self.async_turn_off()
                except (TypeError, ValueError) as ex:
                    _LOGGER.warning("[fan] ⚠️ timer_end_time 解析失败: %s", ex)

        _LOGGER.info(
            "[fan] added: power=%s, fan_speed=%s, Rotate=%s, LRAngle=%s, _properties=%s",
            self.coordinator.device.power,
            self.coordinator.device.fan_speed,
            (self.coordinator.device._properties or {}).get(PROP_ROTATE),
            (self.coordinator.device._properties or {}).get(PROP_LR_ANGLE),
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
        self._cancel_timer()
        self.coordinator.device.power = False
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_timer()
        await super().async_will_remove_from_hass()

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

    # ── 水平摆风（摇头） ──
    @property
    def oscillating(self) -> bool:
        return (self.coordinator.device._properties or {}).get(PROP_ROTATE) == 1

    async def async_oscillate(self, oscillating: bool) -> None:
        """风扇摇头开关。
        
        开启时强制设置为 60° 摆风角度（协议值 12）。
        """
        device = self.coordinator.device
        if device._properties is None:
            device._properties = {}

        if oscillating:
            # 开启摇头：强制设置为 60°（协议值 12）
            updates = {
                PROP_ROTATE: 1,
                PROP_LR_ANGLE: HORIZONTAL_SWING_OPTIONS["60°"],  # 始终是 12
            }
            _LOGGER.info(
                "[fan] 🔄 开启摇头: Rotate=1, LRAngle=%s (60°)",
                HORIZONTAL_SWING_OPTIONS["60°"]
            )
        else:
            # 关闭摇头
            updates = {PROP_ROTATE: 0}
            _LOGGER.info("[fan] 🔄 关闭摇头: Rotate=0")

        # 写入属性并标记为 dirty
        for key, value in updates.items():
            if device._properties.get(key) != value:
                device._properties[key] = value
                if key not in device._dirty:
                    device._dirty.append(key)
        
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

        # 联动更新左右扫风角度选择器的显示
        mac = device.device_info.mac
        select_entity = self.hass.data.get(DOMAIN, {}).get("selects", {}).get(mac)
        if select_entity:
            select_entity.async_write_ha_state()
            _LOGGER.info("[fan] ✅ 已联动更新左右扫风角度选择器")

    # ── 定时（支持分，HA 重启后自动恢复） ──
    @property
    def timer_minutes(self) -> float:
        """剩余分钟数，供 number 实体显示。"""
        if self._timer_end_time is None:
            return 0.0
        now_timestamp = datetime.now(timezone.utc).timestamp()
        remaining = self._timer_end_time - now_timestamp
        return max(0.0, remaining / 60.0)

    @property
    def timer_hours(self) -> float:
        """剩余小时数（兼容）。"""
        return self.timer_minutes / 60.0

    async def async_set_timer(self, hours: float) -> None:
        hours = max(TIMER_MIN, min(TIMER_MAX, hours))
        await self._apply_timer_hours(hours)

    async def async_set_timer_minutes(self, minutes: int | None) -> None:
        """以分钟为单位设置定时（None 或 0 = 取消）。"""
        if minutes is None or minutes <= 0:
            await self._apply_timer_hours(0)
            return
        minutes = max(1, min(TIMER_MAX * 60, minutes))
        await self._apply_timer_hours(minutes / 60.0)

    async def _apply_timer_hours(self, hours: float) -> None:
        """实际设置定时与定时取消逻辑。
        
        使用 UTC 时间戳持久化，确保 HA 重启后能正确恢复倒计时。
        """
        self._cancel_timer()

        if hours > 0:
            seconds = hours * 3600
            # 使用 UTC 时间戳，而不是 loop.time()（单调时钟）
            now_timestamp = datetime.now(timezone.utc).timestamp()
            self._timer_end_time = now_timestamp + seconds
            self._schedule_timer_callback(seconds)
            
            end_time_utc = datetime.fromtimestamp(self._timer_end_time, tz=timezone.utc)
            _LOGGER.info(
                "[fan] ⏱️ 定时 %.2f 小时（%d 分钟），%d 秒后关闭，结束时间: %s",
                hours, int(hours * 60), int(seconds),
                end_time_utc.strftime("%H:%M:%S UTC"),
            )
        else:
            self._timer_end_time = None
            _LOGGER.info("[fan] ⏱️ 定时取消")

        self.async_write_ha_state()

    def _schedule_timer_callback(self, delay_seconds: float) -> None:
        def _on_timer_fire() -> None:
            _LOGGER.info("[fan] ⏰ 定时到，执行关闭")
            self.hass.create_task(self.async_turn_off())

        self._timer_handle = self.hass.loop.call_later(delay_seconds, _on_timer_fire)

    def _cancel_timer(self) -> None:
        if self._timer_handle is not None:
            self._timer_handle.cancel()
            self._timer_handle = None
        self._timer_end_time = None

    @property
    def extra_state_attributes(self) -> dict | None:
        """持久化定时目标时间（UTC 时间戳），HA 重启后可恢复倒计时。
        
        使用 UTC 时间戳而不是 loop.time()（单调时钟），
        确保主机重启后时间基准一致。
        """
        if self._timer_end_time is not None:
            return {"timer_end_time": str(self._timer_end_time)}
        return None
