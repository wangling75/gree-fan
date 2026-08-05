"""Helper and wrapper classes for Gree module."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from greeclimate.device import Device, DeviceInfo
from greeclimate.discovery import Listener
from greeclimate.exceptions import DeviceNotBoundError, DeviceTimeoutError
from greeclimate.network import DeviceProtocol2, Response
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    COORDINATORS,
    DISCOVERY_TIMEOUT,
    DISPATCH_DEVICE_DISCOVERED,
    DOMAIN,
    MAX_ERRORS,
)
from .discovery import FanDiscovery
from .profiles import FanProfile, profile_for_device

_LOGGER = logging.getLogger(__name__)


class FanDevice(Device):
    """Device variant that does not issue an automatic HVAC state query."""

    def __init__(self, device_info: DeviceInfo) -> None:
        super().__init__(device_info)
        # greeclimate declares handlers at class level; isolate them per fan.
        self._handlers = {}

    def handle_device_bound(self, key: str) -> None:
        """Complete binding without scheduling Device.update_state()."""
        DeviceProtocol2.handle_device_bound(self, key)
        self.device_cipher.key = key


class DeviceDataUpdateCoordinator(DataUpdateCoordinator):
    """Manages polling for state changes from the device."""

    def __init__(
        self,
        hass: HomeAssistant,
        device: Device,
        profile: FanProfile,
    ) -> None:
        """Initialize the data update coordinator."""
        DataUpdateCoordinator.__init__(
            self,
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{device.device_info.name}",
            update_interval=timedelta(seconds=60),
        )
        self.device = device
        self.profile = profile
        self._error_count = 0

    def supports(self, prop: str) -> bool:
        """Return whether this device profile supports a property."""
        return self.profile.supports(prop)

    async def _async_update_data(self):
        """Update the state of the device."""
        try:
            fan_state = await self._request_profile_state()
            if self.device._properties is None:
                self.device._properties = {}
            self.device._properties.update(fan_state)
            self._error_count = 0
            return fan_state
        except DeviceNotBoundError as error:
            raise UpdateFailed(f"Device {self.name} is unavailable") from error
        except (DeviceTimeoutError, asyncio.TimeoutError) as error:
            self._error_count += 1

            # Under normal conditions GREE units timeout every once in a while
            if not self.last_update_success or self._error_count >= MAX_ERRORS:
                _LOGGER.warning(
                    "Device is unavailable: %s (%s)",
                    self.name,
                    self.device.device_info,
                )
                raise UpdateFailed(f"Device {self.name} is unavailable") from error

    async def _request_profile_state(self) -> dict:
        """Request and await one profile-specific state response."""
        loop = asyncio.get_running_loop()
        response = loop.create_future()

        def _state_received(data: dict) -> None:
            if not response.done():
                response.set_result(data)

        self.device.add_handler(Response.DATA, _state_received)
        try:
            message = self.device.create_status_message(
                self.device.device_info,
                *self.profile.columns,
            )
            await self.device.send(message)
            return await asyncio.wait_for(response, timeout=10)
        finally:
            self.device.remove_handler(Response.DATA, _state_received)

    async def push_state_update(self):
        """Send state updates to the physical device."""
        try:
            return await self.device.push_state_update()
        except (DeviceTimeoutError, asyncio.TimeoutError):
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

        self.discovery = FanDiscovery(DISCOVERY_TIMEOUT)
        self.discovery.add_listener(self)

        hass.data[DOMAIN].setdefault(COORDINATORS, [])

    async def device_found(self, device_info: DeviceInfo) -> None:
        """Bind and register a positively identified standalone fan."""
        profile = profile_for_device(device_info)
        if profile is None:
            _LOGGER.debug(
                "Ignoring non-fan Gree device: name=%s model=%s mid=%s mac=%s",
                device_info.name,
                device_info.model,
                getattr(device_info, "mid", None),
                device_info.mac,
            )
            return

        # 检查是否已存在（MAC 去重）
        for coordinator in self.hass.data[DOMAIN][COORDINATORS]:
            if coordinator.device.device_info.mac == device_info.mac:
                _LOGGER.debug(
                    "Device already exists: %s (%s), skip duplicate",
                    device_info.name, device_info.mac,
                )
                return

        device = FanDevice(device_info)
        try:
            await device.bind()
        except DeviceNotBoundError:
            _LOGGER.error("Unable to bind to gree device: %s", device_info)
            return
        except DeviceTimeoutError:
            _LOGGER.error("Timeout trying to bind to gree device: %s", device_info)
            return

        _LOGGER.info(
            "Adding Gree fan %s at %s:%i (MAC=%s, MID=%s, speeds=%d)",
            device.device_info.name,
            device.device_info.ip,
            device.device_info.port,
            device.device_info.mac,
            profile.mid,
            profile.speed_count,
        )
        coordinator = DeviceDataUpdateCoordinator(self.hass, device, profile)
        self.hass.data[DOMAIN][COORDINATORS].append(coordinator)
        await coordinator.async_refresh()

        async_dispatcher_send(self.hass, DISPATCH_DEVICE_DISCOVERED, coordinator)

    async def device_update(self, device_info: DeviceInfo) -> None:
        """Handle updates in device information, update if ip has changed."""
        for coordinator in self.hass.data[DOMAIN][COORDINATORS]:
            if coordinator.device.device_info.mac == device_info.mac:
                coordinator.device.device_info.ip = device_info.ip
                await coordinator.async_refresh()
