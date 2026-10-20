"""This module implements communication with BM6 device."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import logging
from typing import Optional

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.scanner import AdvertisementData
from bleak_retry_connector import establish_connection
from Crypto.Cipher import AES

from habluetooth import BaseHaScanner, BluetoothScannerDevice
from homeassistant.components.bluetooth import async_scanner_devices_by_address
from homeassistant.core import HomeAssistant

from .const import (
    BLEAK_CLIENT_TIMEOUT,
    CHARACTERISTIC_UUID_NOTIFY,
    CHARACTERISTIC_UUID_WRITE,
    CRYPT_KEY,
    GATT_DATA_REALTIME,
    GATT_DATA_VERSION,
    GATT_NOTIFY_REALTIME_PREFIX,
    GATT_NOTIFY_VERSION_PREFIX,
)

_LOGGER = logging.getLogger(__name__)


class BM6RealTimeState(Enum):
    """Enumeration for BM6 device status."""

    BatteryOk = 0
    LowVoltage = 1
    Charging = 2


@dataclass
class BM6RealTimeData:
    """Class to store the real-time data read from the BM6 device."""

    Voltage: float = 0.0
    Temperature: int = 0
    Percent: int = 0
    RapidAcceleration: int = 0
    RapidDeceleration: int = 0
    State: BM6RealTimeState = BM6RealTimeState.BatteryOk

    def __init__(self, data: str):
        """Initialize BM6ReadTimeData from a hex string."""
        self.Voltage = int(data[14:18], 16) / 100
        temperature_sign = int(data[6:8], 16)
        self.Temperature = int(data[8:10], 16)
        if temperature_sign == 1:
            self.Temperature = -self.Temperature
        self.Percent = int(data[12:14], 16)
        self.RapidAcceleration = int(data[18:22], 16)
        self.RapidDeceleration = int(data[22:26], 16)
        self.State = int(data[10:12], 16)


@dataclass
class BM6Firmware:
    """Class to store the firmware version of the BM6 device."""

    Version: str = None

    def __init__(self, data: str):
        """Initialize BM6Firmware with version data."""
        self.Version = data


@dataclass
class BM6Advertisement:
    """Class to store advertisement data from the BM6 device."""

    RSSI: int = None
    Scanner: str = None

    def __init__(
        self,
        advertisement_data: Optional[AdvertisementData],
        ha_scanner: Optional[BaseHaScanner],
    ):
        """Initialize BM6Advertisement with advertisement data."""
        self.RSSI = advertisement_data.rssi if advertisement_data else None
        self.Scanner = ha_scanner.name if ha_scanner else None


@dataclass
class BM6Data:
    """Class to store all data read from the BM6 device."""

    Firmware: Optional[BM6Firmware] = None
    RealTime: Optional[BM6RealTimeData] = None
    Advertisement: Optional[BM6Advertisement] = None

    def __init__(
        self,
        advertisement_data: Optional[AdvertisementData],
        ha_scanner: Optional[BaseHaScanner],
    ):
        """Initialize BM6Data with advertisement data."""
        self.Advertisement = BM6Advertisement(advertisement_data, ha_scanner)


class BM6DeviceError(RuntimeError):
    """Raised when communication with a BM6 device fails."""


class BM6Connector:
    """Class to manage the connection to the BM6 device."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        bluetooth_proxy_source: str | None = None,
    ):
        """Initialize the BM6 connector.

        If a source is configured, only that scanner is used. If it is None,
        all available connectable scanners are tried in RSSI order.
        """
        self.hass = hass
        self._address = address
        self._bluetooth_proxy_source = bluetooth_proxy_source
        self._data: BM6Data | None = None

        _LOGGER.debug(
            "Get BM6 device %s using proxy source %s",
            self._address,
            self._bluetooth_proxy_source or "automatic",
        )

        scanners = async_scanner_devices_by_address(
            hass,
            self._address,
            connectable=True,
        )

        if self._bluetooth_proxy_source:
            scanners = [
                scanner
                for scanner in scanners
                if str(getattr(scanner.scanner, "source", ""))
                == str(self._bluetooth_proxy_source)
            ]

        self._scanners: list[BluetoothScannerDevice] = scanners or []

        if not self._scanners:
            if self._bluetooth_proxy_source:
                raise BM6DeviceError(
                    f"Bluetooth device {self._address} not found via proxy "
                    f"source {self._bluetooth_proxy_source}"
                )
            raise BM6DeviceError(f"Bluetooth device {self._address} not found")

        self._scanners.sort(
            key=lambda scanner: scanner.advertisement.rssi,
            reverse=True,
        )
        _LOGGER.debug(
            "BM6 device %s is seen by scanners %s",
            self._address,
            [
                {
                    "scanner": scanner.scanner.name,
                    "source": getattr(scanner.scanner, "source", None),
                    "rssi": scanner.advertisement.rssi,
                }
                for scanner in self._scanners
            ],
        )

    def _decrypt(self, data: bytearray) -> bytearray:
        """Decrypt received data using AES."""
        cipher = AES.new(CRYPT_KEY, AES.MODE_CBC, 16 * b"\0")
        return cipher.decrypt(data)

    def _encrypt(self, data: bytearray) -> bytearray:
        """Encrypt data to send using AES."""
        cipher = AES.new(CRYPT_KEY, AES.MODE_CBC, 16 * b"\0")
        return cipher.encrypt(data)

    async def _notify_callback(
        self,
        sender: BleakGATTCharacteristic,
        data: bytearray,
    ) -> None:
        """Handle notifications from the BM6 device."""
        message = self._decrypt(data).hex()
        _LOGGER.debug("Received data from BM6 %s: %s", self._address, message)
        if message.startswith(GATT_NOTIFY_REALTIME_PREFIX):
            self._data.RealTime = BM6RealTimeData(message)
            _LOGGER.debug(
                "Decoded real-time data from BM6 %s: %s",
                self._address,
                self._data.RealTime,
            )
        elif message.startswith(GATT_NOTIFY_VERSION_PREFIX):
            self._data.Firmware = BM6Firmware(message)
            _LOGGER.debug(
                "Decoded firmware version from BM6 %s: %s",
                self._address,
                self._data.Firmware,
            )

    async def get_data(self) -> BM6Data:
        """Retrieve data from the BM6 device."""
        exceptions: list[Exception] = []

        for scanner in self._scanners:
            scanner_name = scanner.scanner.name
            _LOGGER.debug(
                "Start getting data from BM6 %s via scanner %s (source %s)",
                self._address,
                scanner_name,
                getattr(scanner.scanner, "source", None),
            )
            try:
                self._data = BM6Data(
                    scanner.advertisement,
                    scanner.scanner,
                )

                client: BleakClient = await establish_connection(
                    BleakClient,
                    scanner.ble_device,
                    scanner_name,
                    timeout=BLEAK_CLIENT_TIMEOUT,
                    use_services_cache=False,
                )

                try:
                    self._data.RealTime = None
                    await client.write_gatt_char(
                        CHARACTERISTIC_UUID_WRITE,
                        self._encrypt(bytearray.fromhex(GATT_DATA_REALTIME)),
                        response=True,
                    )
                    await client.start_notify(
                        CHARACTERISTIC_UUID_NOTIFY,
                        self._notify_callback,
                    )
                    elapsed = 0.0
                    while self._data.RealTime is None:
                        await asyncio.sleep(0.1)
                        elapsed += 0.1
                        if elapsed >= BLEAK_CLIENT_TIMEOUT:
                            raise BM6DeviceError(
                                f"Timeout waiting for notification from BM6 at {self._address}"
                            )
                    await client.stop_notify(CHARACTERISTIC_UUID_NOTIFY)
                finally:
                    await client.disconnect()

            except Exception as err:
                err.add_note(f"Using scanner {scanner_name}")
                exceptions.append(err)
                _LOGGER.warning(
                    "Error while reading BM6 at %s via %s: %s",
                    self._address,
                    scanner_name,
                    err,
                )
                continue

            if self._data and self._data.RealTime:
                return self._data

        if exceptions:
            raise BM6DeviceError(
                f"Error while reading BM6 at {self._address}: {exceptions}"
            ) from exceptions[0]
        raise BM6DeviceError(f"Error while reading BM6 at {self._address}")
