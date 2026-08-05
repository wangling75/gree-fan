"""Helper and wrapper classes for Gree module."""
from __future__ import annotations

from datetime import timedelta
import logging

from greeclimate import network
from greeclimate.device import Device, DeviceInfo
from greeclimate.discovery import Discovery, Listener
from greeclimate.exceptions import DeviceNotBoundError, DeviceTimeoutError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    COORDINATORS,
    DISCOVERY_TIMEOUT,
    DISPATCH_DEVICE_DISCOVERED,
    DOMAIN,
    MAX_ERRORS,
    PROP_LR_ANGLE,
    PROP_ROTATE,
    PROP_SW_UP_DOWN,
    PROP_TIMER_ACTION,
    PROP_TIMER_HOUR,
    PROP_TIMER_MINUTE,
    PROP_TIMER_ON,
)

_LOGGER = logging.getLogger(__name__)


class DeviceDataUpdateCoordinator(DataUpdateCoordinator):
    """Manages polling for state changes from the device."""

    def __init__(self, hass: HomeAssistant, device: Device) -> None:
        """Initialize the data update coordinator."""
        DataUpdateCoordinator.__init__(
            self,
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{device.device_info.name}",
            update_interval=timedelta(seconds=60),
        )
        self.device = device
        self._error_count = 0

    async def _async_update_data(self):
        """Update the state of the device."""
        try:
            await self.device.update_state()
            # greeclimate 1.4.1 不读取风扇的摆风角度和原生定时
            # 字段，需要单独读取并合并状态。
            fan_extra_state = await network.request_state(
                [
                    PROP_ROTATE,
                    PROP_LR_ANGLE,
                    PROP_SW_UP_DOWN,
                    PROP_TIMER_ON,
                    PROP_TIMER_ACTION,
                    PROP_TIMER_HOUR,
                    PROP_TIMER_MINUTE,
                ],
                self.device.device_info,
                self.device.device_key,
            )
            self.device._properties.update(fan_extra_state)
            
            # 成功轮询后重置错误计数
            self._error_count = 0
        except DeviceNotBoundError as error:
            raise UpdateFailed(f"Device {self.name} is unavailable") from error
        except DeviceTimeoutError as error:
            self._error_count += 1

            # Under normal conditions GREE units timeout every once in a while
            if self.last_update_success and self._error_count >= MAX_ERRORS:
                _LOGGER.warning(
                    "Device is unavailable: %s (%s)",
                    self.name,
                    self.device.device_info,
                )
                raise UpdateFailed(f"Device {self.name} is unavailable") from error

    async def push_state_update(self):
        """Send state updates to the physical device."""
        try:
            return await self.device.push_state_update()
        except DeviceTimeoutError:
            _LOGGER.warning(
                "Timeout send state update to: %s (%s)",
                self.name,
                self.device.device_info,
            )


class DiscoveryService(Listener):
    """Discovery event handler for gree devices."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize discovery service."""
        super().__init__()
        self.hass = hass

        self.discovery = Discovery(DISCOVERY_TIMEOUT)
        self.discovery.add_listener(self)

        hass.data[DOMAIN].setdefault(COORDINATORS, [])

    async def device_found(self, device_info: DeviceInfo) -> None:
        """Handle new device found on the network.
        
        检查设备是否已存在（通过 MAC 去重），并筛选只添加风扇设备。
        """
        # 检查是否已存在（MAC 去重）
        for coordinator in self.hass.data[DOMAIN][COORDINATORS]:
            if coordinator.device.device_info.mac == device_info.mac:
                _LOGGER.debug(
                    "Device already exists: %s (%s), skip duplicate",
                    device_info.name, device_info.mac,
                )
                return

        device = Device(device_info)
        try:
            await device.bind()
        except DeviceNotBoundError:
            _LOGGER.error("Unable to bind to gree device: %s", device_info)
            return
        except DeviceTimeoutError:
            _LOGGER.error("Timeout trying to bind to gree device: %s", device_info)
            return

        # 筛选：只添加风扇设备，排除空调
        # greeclimate 的 DeviceInfo 应该有设备类型字段
        # 检查 device_info 中的属性来判断设备类型
        device_type = getattr(device_info, 'hvac_type', None) or getattr(device_info, 'type', None)
        
        # 如果有设备类型信息，判断是否为风扇
        # 注意：如果没有 hvac_type 字段，可以通过其他属性判断（如型号、名称等）
        if device_type and str(device_type).lower() not in ('fan', '风扇'):
            _LOGGER.info(
                "Skipping non-fan device: %s (type=%s)",
                device_info.name, device_type,
            )
            return
        
        # 备选方案：通过设备名称或型号判断（如果 greeclimate 没有 hvac_type）
        device_name = device_info.name.lower()
        if '空调' in device_name or 'ac' in device_name or 'air conditioner' in device_name:
            _LOGGER.info(
                "Skipping non-fan device (detected by name): %s",
                device_info.name,
            )
            return

        _LOGGER.info(
            "Adding Gree fan device %s at %s:%i (MAC: %s)",
            device.device_info.name,
            device.device_info.ip,
            device.device_info.port,
            device.device_info.mac,
        )
        coordo = DeviceDataUpdateCoordinator(self.hass, device)
        self.hass.data[DOMAIN][COORDINATORS].append(coordo)
        await coordo.async_refresh()

        async_dispatcher_send(self.hass, DISPATCH_DEVICE_DISCOVERED, coordo)

    async def device_update(self, device_info: DeviceInfo) -> None:
        """Handle updates in device information, update if ip has changed."""
        for coordinator in self.hass.data[DOMAIN][COORDINATORS]:
            if coordinator.device.device_info.mac == device_info.mac:
                coordinator.device.device_info.ip = device_info.ip
                await coordinator.async_refresh()
