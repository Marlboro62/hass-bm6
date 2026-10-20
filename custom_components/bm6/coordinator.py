"""BM6 data update coordinator."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .battery import Battery
from .bm6_connect import BM6Connector, BM6Data, BM6DeviceError
from .const import (
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

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=config_entry.data[CONF_UPDATE_INTERVAL]
            ),
        )

    async def _async_update_data(self) -> dict:
        """Fetch data from the BM6 device."""
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
