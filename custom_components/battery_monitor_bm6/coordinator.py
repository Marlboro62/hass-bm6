"""BM6 data update coordinator."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .battery import Battery
from .bm6_connect import BM6Connector, BM6Data, BM6DeviceError
from .const import (
    BACKOFF_FACTORS,
    MAX_BACKOFF_SECONDS,
    AUTO_PROXY_SOURCE,
    CONF_BLUETOOTH_PROXY,
    CONF_DEVICE_ADDRESS,
    CONF_TEMPERATURE_OFFSET,
    CONF_TEMPERATURE_UNIT,
    CONF_UPDATE_INTERVAL,
    CONF_VOLTAGE_OFFSET,
    DOMAIN,
    KEY_BLUETOOTH_SCANNER,
    KEY_CVR_MAX,
    KEY_CVR_MIN,
    KEY_DEVICE_PERCENTAGE,
    KEY_DEVICE_STATE,
    KEY_DVR_MAX,
    KEY_DVR_MIN,
    KEY_PERCENTAGE,
    KEY_RAPID_ACCELERATION,
    KEY_RAPID_DECELERATION,
    KEY_RSSI,
    KEY_SOC_MAX,
    KEY_SOC_MIN,
    KEY_SOD_MAX,
    KEY_SOD_MIN,
    KEY_STATE,
    KEY_STATE_ALGORITHM,
    KEY_TEMPERATURE_CORRECTED,
    KEY_TEMPERATURE_DEVICE,
    KEY_TEMPERATURE_UNIT,
    KEY_VOLTAGE_CORRECTED,
    KEY_VOLTAGE_DEVICE,
)
from .utils import convert_temperature

if TYPE_CHECKING:
    from . import BM6ConfigEntry

_LOGGER = logging.getLogger(__name__)


class BM6DataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the BM6 device."""

    def __init__(self, hass: HomeAssistant, config_entry: BM6ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.config_entry = config_entry
        self.device_address = config_entry.data[CONF_DEVICE_ADDRESS]
        self._battery = Battery(config_entry.data)

        configured_proxy = config_entry.data.get(CONF_BLUETOOTH_PROXY)
        self.bluetooth_proxy_source = (
            None
            if configured_proxy in (None, "", AUTO_PROXY_SOURCE)
            else configured_proxy
        )

        # échecs successifs et moment (horloge monotone) avant lequel aucune lecture n'est tentée
        self._failures = 0
        self._next_attempt: float | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=config_entry.data[CONF_UPDATE_INTERVAL]
            ),
        )

    def _record_failure(self) -> None:
        """Échec : la lecture suivante est repoussée de plus en plus (jusqu'à MAX_BACKOFF_SECONDS)."""
        self._failures += 1
        factor = BACKOFF_FACTORS[min(self._failures, len(BACKOFF_FACTORS)) - 1]
        interval = self.update_interval.total_seconds() if self.update_interval else 120
        delay = min(interval * factor, MAX_BACKOFF_SECONDS)
        # un peu moins que le délai : la lecture planifiée qui tombe juste après l'échéance n'est pas sautée
        self._next_attempt = time.monotonic() + max(0.0, delay - min(interval / 2, 30))

    async def _async_update_data(self) -> dict:
        """Fetch data from the BM6 device."""
        # échecs récents : ne pas solliciter de nouveau les proxys avant le moment prévu (rien de journalisé)
        if self._next_attempt is not None and time.monotonic() < self._next_attempt:
            raise UpdateFailed(
                f"BM6 {self.device_address} : lecture en attente après {self._failures} échec(s), "
                f"nouvel essai dans {int(self._next_attempt - time.monotonic())} s"
            )
        try:
            data = await self._read()
        except UpdateFailed:
            self._record_failure()
            raise
        self._failures = 0
        self._next_attempt = None
        return data

    async def _read(self) -> dict:
        """Lecture du BM6 (une connexion)."""
        try:
            connector = BM6Connector(
                hass=self.hass,
                address=self.device_address,
                bluetooth_proxy_source=self.bluetooth_proxy_source,
            )
            data: BM6Data = await connector.get_data()

            voltage_corrected = (
                data.RealTime.Voltage
                + self.config_entry.data[CONF_VOLTAGE_OFFSET]
            )
            temperature_unit = self.config_entry.data[CONF_TEMPERATURE_UNIT]
            temperature_corrected = (
                convert_temperature(
                    data.RealTime.Temperature,
                    temperature_unit,
                )
                + self.config_entry.data[CONF_TEMPERATURE_OFFSET]
            )

            self._battery.update(data.RealTime, voltage_corrected)

            return {
                KEY_VOLTAGE_DEVICE: data.RealTime.Voltage,
                KEY_VOLTAGE_CORRECTED: voltage_corrected,
                KEY_TEMPERATURE_DEVICE: data.RealTime.Temperature,
                KEY_TEMPERATURE_UNIT: temperature_unit,
                KEY_TEMPERATURE_CORRECTED: temperature_corrected,
                KEY_PERCENTAGE: self._battery.percent,
                KEY_STATE: self._battery.state.value,
                KEY_RSSI: data.Advertisement.RSSI if data.Advertisement else None,
                KEY_DVR_MIN: self._battery.range.dvr.min,
                KEY_DVR_MAX: self._battery.range.dvr.max,
                KEY_CVR_MIN: self._battery.range.cvr.min,
                KEY_CVR_MAX: self._battery.range.cvr.max,
                KEY_SOD_MIN: self._battery.range.sod.min,
                KEY_SOD_MAX: self._battery.range.sod.max,
                KEY_SOC_MIN: self._battery.range.soc.min,
                KEY_SOC_MAX: self._battery.range.soc.max,
                KEY_STATE_ALGORITHM: self._battery.info.state_algorithm.value,
                KEY_DEVICE_PERCENTAGE: data.RealTime.Percent,
                KEY_DEVICE_STATE: data.RealTime.State,
                KEY_RAPID_ACCELERATION: data.RealTime.RapidAcceleration,
                KEY_RAPID_DECELERATION: data.RealTime.RapidDeceleration,
                KEY_BLUETOOTH_SCANNER: (
                    data.Advertisement.Scanner
                    if data.Advertisement
                    else None
                ),
            }
        except BM6DeviceError as err:
            _LOGGER.error(
                "BM6 device error at %s: %s",
                self.device_address,
                err,
            )
            raise UpdateFailed(f"BM6 device error: {err}") from err
        except Exception as err:
            _LOGGER.error(
                "Unexpected error while reading BM6 at %s: %s",
                self.device_address,
                err,
            )
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def get_diagnostic_data(self) -> dict:
        """Return diagnostic data for the BM6 device."""
        return {
            "device_address": self.device_address,
            "bluetooth_proxy_source": self.bluetooth_proxy_source,
            "battery": self._battery.get_diagnostic_data(),
            "data": self.data,
            "last_update_success": self.last_update_success,
            "last_exception": self.last_exception,
            "update_interval": self.update_interval.seconds,
        }
