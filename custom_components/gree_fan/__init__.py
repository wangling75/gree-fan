"""The Gree XFan integration - 格力风扇插件."""
import logging
from datetime import timedelta

from homeassistant.components.network import async_get_ipv4_broadcast_addresses
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .bridge import DiscoveryService
from .const import (
    COORDINATORS,
    DATA_DISCOVERY_INTERVAL,
    DATA_DISCOVERY_SERVICE,
    DISCOVERY_SCAN_INTERVAL,
    DISPATCHERS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# 只加载风扇平台，移除了空调平台
PLATFORMS = [Platform.FAN, Platform.SELECT, Platform.SWITCH, Platform.TEXT]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gree XFan from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    gree_discovery = DiscoveryService(hass)
    domain_data[DATA_DISCOVERY_SERVICE] = gree_discovery

    domain_data.setdefault(DISPATCHERS, [])
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _async_scan_update(_=None):
        bcast_addr = list(await async_get_ipv4_broadcast_addresses(hass))
        await gree_discovery.discovery.scan(0, bcast_ifaces=bcast_addr)

    _LOGGER.debug("Scanning network for Gree devices")
    await _async_scan_update()

    hass.data[DOMAIN][DATA_DISCOVERY_INTERVAL] = async_track_time_interval(
        hass, _async_scan_update, timedelta(seconds=DISCOVERY_SCAN_INTERVAL)
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if hass.data[DOMAIN].get(DISPATCHERS) is not None:
        for cleanup in hass.data[DOMAIN][DISPATCHERS]:
            cleanup()

    if hass.data[DOMAIN].get(DATA_DISCOVERY_INTERVAL) is not None:
        hass.data[DOMAIN].pop(DATA_DISCOVERY_INTERVAL)()

    if hass.data[DOMAIN].get(DATA_DISCOVERY_SERVICE) is not None:
        discovery_service = hass.data[DOMAIN].pop(DATA_DISCOVERY_SERVICE)
        discovery_service.discovery.close()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        for coordinator in hass.data[DOMAIN].get(COORDINATORS, []):
            coordinator.device.close()
        hass.data[DOMAIN].pop(COORDINATORS, None)
        hass.data[DOMAIN].pop(DISPATCHERS, None)

    return unload_ok
