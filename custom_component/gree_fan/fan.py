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
    COORDINATORS,
    DISPATCH_DEVICE_DISCOVERED,
    DISPATCHERS,
    DOMAIN,
    PROP_LR_ANGLE,
    PROP_ROTATE,
    PROP_TIMER_ACTION,
    PROP_TIMER_HOUR,
    PROP_TIMER_MINUTE,
    PROP_TIMER_ON,
    TIMER_ACTION_TURN_OFF,
    TIMER_MAX,
    TIMER_MIN,
)

_LOGGER = logging.getLogger(__name__)

MODE_NORMAL = 0


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
    """Standalone Gree fan with profile-driven capabilities."""

    _attr_has_entity_name = False
    _attr_name: str | None = None

    def __init__(self, coordinator: DeviceDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._timer_handle: asyncio.TimerHandle | None = None
        self._timer_end_time: float | None = None
        self._speed_range = (1, coordinator.profile.speed_count)
        self._preset_mode_values = dict(coordinator.profile.preset_modes)
        self._preset_modes_reverse = {
            value: name for name, value in self._preset_mode_values.items()
        }
        self._attr_speed_count = coordinator.profile.speed_count
        self._attr_preset_modes = list(self._preset_mode_values)
        features = FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
        if coordinator.supports("WdSpd"):
            features |= FanEntityFeature.SET_SPEED
        if self._preset_mode_values:
            features |= FanEntityFeature.PRESET_MODE
        if coordinator.supports(PROP_ROTATE):
            features |= FanEntityFeature.OSCILLATE
        self._attr_supported_features = features
        self._attr_name = coordinator.device.device_info.name
        mac = coordinator.device.device_info.mac
        self._attr_unique_id = mac
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, mac)},
            identifiers={(DOMAIN, mac)},
            manufacturer="Gree",
            name=self._attr_name,
            model=coordinator.device.device_info.model or coordinator.profile.mid,
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

        # 优先从风扇的原生定时字段恢复。设备未上报定时字段
        # 时，才使用 HA 中保存的结束时间作为兼容兜底。
        properties = self.coordinator.device._properties or {}
        native_timer_available = PROP_TIMER_ON in properties
        native_minutes = (
            self._native_timer_minutes(properties) if native_timer_available else 0
        )
        if native_minutes > 0:
            self._timer_end_time = (
                datetime.now(timezone.utc).timestamp() + native_minutes * 60
            )
            self._schedule_timer_callback(native_minutes * 60)
            _LOGGER.info(
                "[fan] 从设备恢复关机定时: TmrHour=%s, TmrMin=%s",
                properties.get(PROP_TIMER_HOUR),
                properties.get(PROP_TIMER_MINUTE),
            )
        elif self.supports_native_timer and not native_timer_available:
            state = self.hass.states.get(self.entity_id)
            if state and state.attributes:
                raw = state.attributes.get("timer_end_time")
                if raw:
                    try:
                        timer_end_timestamp = float(raw)
                        now_timestamp = datetime.now(timezone.utc).timestamp()
                        remaining = timer_end_timestamp - now_timestamp
                        if remaining > 0:
                            self._timer_end_time = timer_end_timestamp
                            self._schedule_timer_callback(remaining)
                        else:
                            await self.async_turn_off()
                    except (TypeError, ValueError) as ex:
                        _LOGGER.warning("[fan] timer_end_time 解析失败: %s", ex)

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

    @property
    def percentage(self) -> int | None:
        """Return the current profile-adjusted speed percentage."""
        speed = self.coordinator.device.fan_speed
        if speed is None:
            return None
        if not self.is_on:
            return 0
        normalized_speed = max(
            self._speed_range[0],
            min(self._speed_range[1], int(speed)),
        )
        return ranged_value_to_percentage(self._speed_range, normalized_speed)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
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
            speed = round(percentage_to_ranged_value(self._speed_range, percentage))
            device.fan_speed = speed

        _LOGGER.info(
            "[fan] turn_on: _dirty=%s key=%s ip=%s",
            device._dirty, device.device_key, device.device_info.ip,
        )
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: t.Any) -> None:
        _LOGGER.info("[fan] 🔴 turn_off: _dirty=%s", self.coordinator.device._dirty)
        self._cancel_local_timer()
        device = self.coordinator.device
        if self.supports_native_timer:
            self._set_native_timer_properties(0)
        device.power = False
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        # 卸载集成时只移除 HA 兜底回调，不取消设备中的定时。
        self._cancel_local_timer()
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

        speed = round(percentage_to_ranged_value(self._speed_range, percentage))
        device.fan_speed = speed

        _LOGGER.info(
            "[fan] 🎚️ set_percentage: %d%% → speed=%d _dirty=%s",
            percentage, speed, device._dirty,
        )
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    # ── 模式 ──
    @property
    def preset_mode(self) -> str | None:
        if not self.coordinator.device.power:
            return None
        return self._preset_modes_reverse.get(self.coordinator.device.mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self.preset_modes:
            raise ValueError(f"无效模式: {preset_mode}")
        device = self.coordinator.device
        device.power = True
        device.mode = self._preset_mode_values[preset_mode]
        _LOGGER.info(
            "[fan] set_preset_mode: %s (mode=%d)",
            preset_mode,
            self._preset_mode_values[preset_mode],
        )
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    # ── 水平摆风（摇头） ──
    @property
    def oscillating(self) -> bool:
        return (self.coordinator.device._properties or {}).get(PROP_ROTATE) == 1

    async def async_oscillate(self, oscillating: bool) -> None:
        """Set horizontal oscillation using only supported properties."""
        device = self.coordinator.device
        if device._properties is None:
            device._properties = {}

        if oscillating:
            updates = {PROP_ROTATE: 1}
            if self.coordinator.supports(PROP_LR_ANGLE):
                current_angle = device._properties.get(PROP_LR_ANGLE)
                if isinstance(current_angle, int) and current_angle > 0:
                    updates[PROP_LR_ANGLE] = current_angle
                elif self.coordinator.profile.horizontal_angles:
                    updates[PROP_LR_ANGLE] = self.coordinator.profile.horizontal_angles[0][1]
            _LOGGER.info("[fan] 开启左右摆风: %s", updates)
        else:
            updates = {PROP_ROTATE: 0}
            _LOGGER.info("[fan] 关闭左右摆风")

        # 同一状态也重新发送，避免设备实际状态与缓存不一致。
        for key, value in updates.items():
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
        if not self.supports_native_timer:
            raise ValueError("该风扇型号不支持原生定时")
        hours = max(TIMER_MIN, min(TIMER_MAX, hours))
        await self._apply_timer_hours(hours)

    async def async_set_timer_minutes(self, minutes: int | None) -> None:
        """以分钟为单位设置定时（None 或 0 = 取消）。"""
        if not self.supports_native_timer:
            raise ValueError("该风扇型号不支持原生定时")
        if minutes is None or minutes <= 0:
            await self._apply_timer_hours(0)
            return
        minutes = max(1, min(TIMER_MAX * 60, minutes))
        await self._apply_timer_hours(minutes / 60.0)

    async def _apply_timer_hours(self, hours: float) -> None:
        """设置设备原生关机定时，并保留 HA 本地回调作为兜底."""
        self._cancel_local_timer()
        total_minutes = max(0, min(TIMER_MAX * 60, round(hours * 60)))
        self._set_native_timer_properties(total_minutes)
        await self.coordinator.push_state_update()

        if total_minutes > 0:
            seconds = total_minutes * 60
            now_timestamp = datetime.now(timezone.utc).timestamp()
            self._timer_end_time = now_timestamp + seconds
            self._schedule_timer_callback(seconds)

            end_time_utc = datetime.fromtimestamp(self._timer_end_time, tz=timezone.utc)
            _LOGGER.info(
                "[fan] 设备关机定时已设置: %d 分钟，结束时间: %s",
                total_minutes,
                end_time_utc.strftime("%H:%M:%S UTC"),
            )
        else:
            self._timer_end_time = None
            _LOGGER.info("[fan] 设备关机定时已取消")

        self.async_write_ha_state()

    @staticmethod
    def _native_timer_minutes(properties: dict) -> int:
        """从风扇上报字段读取剩余的原生关机定时."""
        if properties.get(PROP_TIMER_ON) != 1:
            return 0
        if properties.get(PROP_TIMER_ACTION) not in (None, TIMER_ACTION_TURN_OFF):
            return 0
        try:
            hours = int(properties.get(PROP_TIMER_HOUR) or 0)
            minutes = int(properties.get(PROP_TIMER_MINUTE) or 0)
        except (TypeError, ValueError):
            return 0
        return max(0, hours * 60 + minutes)

    @property
    def supports_native_timer(self) -> bool:
        """Return whether all native timer fields are supported."""
        return all(
            self.coordinator.supports(prop)
            for prop in (
                PROP_TIMER_ON,
                PROP_TIMER_ACTION,
                PROP_TIMER_HOUR,
                PROP_TIMER_MINUTE,
            )
        )

    def _set_native_timer_properties(self, total_minutes: int) -> None:
        """将风扇原生定时的四个字段放入同一条控制命令."""
        device = self.coordinator.device
        if device._properties is None:
            device._properties = {}

        enabled = total_minutes > 0
        hours, minutes = divmod(total_minutes, 60) if enabled else (0, 0)
        updates = {
            PROP_TIMER_ON: int(enabled),
            PROP_TIMER_ACTION: TIMER_ACTION_TURN_OFF,
            PROP_TIMER_HOUR: hours,
            PROP_TIMER_MINUTE: minutes,
        }
        # 值与缓存相同时也要四项同包发送，设备才会重新计时。
        for key, value in updates.items():
            device._properties[key] = value
            if key not in device._dirty:
                device._dirty.append(key)

        _LOGGER.info(
            "[fan] 原生定时命令: TmrOn=%d, TmrAction=%d, TmrHour=%d, TmrMin=%d",
            updates[PROP_TIMER_ON],
            updates[PROP_TIMER_ACTION],
            updates[PROP_TIMER_HOUR],
            updates[PROP_TIMER_MINUTE],
        )

    def _schedule_timer_callback(self, delay_seconds: float) -> None:
        def _on_timer_fire() -> None:
            self._timer_handle = None
            _LOGGER.info("[fan] HA 兜底定时到，确认关闭风扇")
            self.hass.create_task(self.async_turn_off())

        self._timer_handle = self.hass.loop.call_later(delay_seconds, _on_timer_fire)

    def _cancel_local_timer(self) -> None:
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
