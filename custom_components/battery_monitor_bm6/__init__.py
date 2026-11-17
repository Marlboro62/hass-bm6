"""
This module sets up the BM6 component for Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
import logging
from awesomeversion import AwesomeVersion

from homeassistant.const import __version__ as HA_VERSION

from .const import MIN_REQUIRED_HA_VERSION, PLATFORMS
from .coordinator import BM6DataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry


@dataclass
class BM6Data:
    """Holds global data for BM6."""

    coordinator: BM6DataUpdateCoordinator


type BM6ConfigEntry = ConfigEntry[BM6Data]

_LOGGER = logging.getLogger(__name__)


def is_ha_supported() -> bool:
    """Return True, if current HA version is supported."""
    if AwesomeVersion(HA_VERSION) >= MIN_REQUIRED_HA_VERSION:
        return True
    _LOGGER.error(
        'Unsupported HA version! Please upgrade home assistant at least to "%s"',
        MIN_REQUIRED_HA_VERSION,
    )
    return False


async def async_setup(
        hass: HomeAssistant,
        config: dict
):
    """Set up the BM6 component."""
    _LOGGER.debug("BM6 component is set up")
    return True


async def async_setup_entry(
        hass: HomeAssistant,
        entry: BM6ConfigEntry
) -> bool:
    """Set up BM6 from a config entry."""
    if not is_ha_supported():
        return False
    coordinator = BM6DataUpdateCoordinator(hass, entry)
    entry.runtime_data = BM6Data(coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    # Première lecture en tâche de fond : une connexion Bluetooth lente ou un BM6
    # hors de portée ne retarde plus le démarrage de Home Assistant. La tâche est
    # annulée automatiquement si l'entrée est déchargée.
    entry.async_create_background_task(
        hass,
        coordinator.async_refresh(),
        name=f"{entry.domain}_first_refresh_{entry.entry_id}",
    )
    return True


async def async_unload_entry(
        hass: HomeAssistant,
        entry: BM6ConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
        hass: HomeAssistant,
        entry: BM6ConfigEntry
) -> None:
    """Reload the config entry when it changed."""
    await hass.config_entries.async_reload(entry.entry_id)
