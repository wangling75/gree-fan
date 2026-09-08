"""Discovery that preserves fan classification fields from scan packets."""
from __future__ import annotations

import logging

from greeclimate.device import DeviceInfo
from greeclimate.discovery import Discovery

_LOGGER = logging.getLogger(__name__)


class FanDiscovery(Discovery):
    """Gree discovery retaining MID and category data discarded by the library."""

    def close(self) -> None:
        """Close the discovery socket when it was successfully created."""
        if self._transport is not None:
            super().close()

    def packet_received(self, obj, addr) -> None:
        """Convert one decoded scan packet into an enriched DeviceInfo."""
        pack = obj.get("pack")
        if not pack:
            _LOGGER.error("Received an unexpected response during discovery")
            return

        device_info = DeviceInfo(
            addr[0],
            addr[1],
            pack.get("mac") or pack.get("cid"),
            pack.get("name"),
            pack.get("brand"),
            pack.get("model"),
            pack.get("ver"),
        )
        device_info.mid = pack.get("mid")
        device_info.catalog = pack.get("catalog")
        device_info.series = pack.get("series")
        self._create_task(self.device_found(device_info))
