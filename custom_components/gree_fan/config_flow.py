"""Config flow for Gree standalone fans."""

from homeassistant.components.network import async_get_ipv4_broadcast_addresses
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_flow

from .const import DISCOVERY_TIMEOUT, DOMAIN
from .discovery import FanDiscovery
from .profiles import profile_for_device


async def _async_has_devices(hass: HomeAssistant) -> bool:
    """Return if there are devices that can be discovered."""
    gree_discovery = FanDiscovery(DISCOVERY_TIMEOUT)
    bcast_addr = list(await async_get_ipv4_broadcast_addresses(hass))
    try:
        devices = await gree_discovery.scan(
            wait_for=DISCOVERY_TIMEOUT, bcast_ifaces=bcast_addr
        )
        return any(profile_for_device(device) is not None for device in devices)
    finally:
        gree_discovery.close()


config_entry_flow.register_discovery_flow(DOMAIN, "Gree XFan", _async_has_devices)
