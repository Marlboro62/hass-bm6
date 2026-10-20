"""Config flow for BM6 integration."""

from __future__ import annotations

from enum import Enum
import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import async_discovered_service_info
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.loader import async_get_integration
from home_assistant_bluetooth import BluetoothServiceInfoBleak

from .battery import (
    Battery,
    BatteryStateAlgorithm,
    BatteryType,
    BatteryVoltage,
    battery_voltage_ranges,
)
from .const import (
    AUTO_PROXY_SOURCE,
    CONF_BATTERY_TYPE,
    CONF_BATTERY_VOLTAGE,
    CONF_BLUETOOTH_PROXY,
    CONF_CUSTOM_CVR_MAX,
    CONF_CUSTOM_CVR_MIN,
    CONF_CUSTOM_DVR_MAX,
    CONF_CUSTOM_DVR_MIN,
    CONF_CUSTOM_SOC_MAX,
    CONF_CUSTOM_SOC_MIN,
    CONF_CUSTOM_SOD_MAX,
    CONF_CUSTOM_SOD_MIN,
    CONF_DEVICE_ADDRESS,
    CONF_STATE_ALGORITHM,
    CONF_TEMPERATURE_OFFSET,
    CONF_TEMPERATURE_UNIT,
    CONF_UPDATE_INTERVAL,
    CONF_VOLTAGE_OFFSET,
    DEFAULT_TEMPERATURE_OFFSET,
    DEFAULT_TEMPERATURE_UNIT,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VOLTAGE_OFFSET,
    DOMAIN,
    ERROR_CVR_LESS_THAN_DVR,
    ERROR_MAX_LESS_THAN_MIN,
    ERROR_SOC_LESS_THAN_SOD,
    MIN_UPDATE_INTERVAL,
    TRANSLATION_KEY_BATTERY_STATE_ALGORITHM,
    TRANSLATION_KEY_BATTERY_TYPE,
    TRANSLATION_KEY_BATTERY_VOLTAGE,
)

if TYPE_CHECKING:
    from . import BM6ConfigEntry

_LOGGER = logging.getLogger(__name__)

DEFAULT_BATTERY_VOLTAGE = BatteryVoltage.V12
DEFAULT_BATTERY_TYPE = BatteryType.AGM
DEFAULT_STATE_ALGORITHM = BatteryStateAlgorithm.SoC_SoD

AUTO_PROXY_LABEL = "Automatique (meilleur proxy disponible)"


class ConfigPage(Enum):
    """Config page for BM6 config flow."""

    MAIN = "main"
    CUSTOM_CALCULATION = "custom_calculation"
    CUSTOM_VOLTAGE = "custom_voltage"


def get_bluetooth_proxy_choices(hass: HomeAssistant) -> list[dict[str, str]]:
    """Return active Bluetooth scanners as stable source/label choices.

    The scanner source is normally the stable Bluetooth source address of the
    adapter or ESPHome Bluetooth proxy. The display name is only a label and
    is never stored as the proxy identifier.
    """
    choices: list[dict[str, str]] = []
    automatic_choice = {"value": AUTO_PROXY_SOURCE, "label": AUTO_PROXY_LABEL}
    seen_sources: set[str] = set()

    for scanner in bluetooth.async_current_scanners(hass):
        source = getattr(scanner, "source", None)
        if not source or source in seen_sources:
            continue

        name = getattr(scanner, "name", None) or source
        choices.append(
            {
                "value": str(source),
                "label": f"{name} ({source})",
            }
        )
        seen_sources.add(source)

    choices.sort(key=lambda item: item["label"].lower())
    return [automatic_choice, *choices]


async def build_schema(
    hass: HomeAssistant,
    data: dict[str, Any],
    devices: dict[str, Any] | None,
    is_options_flow: bool,
    config_page: ConfigPage,
) -> vol.Schema:
    """Build the schema for config and options flows."""
    schema_fields: dict[Any, Any] = {}

    if config_page == ConfigPage.MAIN:
        if not is_options_flow:
            schema_fields[vol.Required(CONF_DEVICE_ADDRESS)] = vol.In(devices or {})

        proxy_choices = get_bluetooth_proxy_choices(hass)
        proxy_values = [choice["value"] for choice in proxy_choices]
        saved_proxy = data.get(CONF_BLUETOOTH_PROXY)
        default_proxy = saved_proxy if saved_proxy in proxy_values else proxy_values[0]

        schema_fields.update(
            {
                vol.Required(
                    CONF_BLUETOOTH_PROXY,
                    default=default_proxy,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=proxy_choices,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_STATE_ALGORITHM,
                    default=data.get(
                        CONF_STATE_ALGORITHM,
                        DEFAULT_STATE_ALGORITHM.value,
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[option.value for option in BatteryStateAlgorithm],
                        translation_key=TRANSLATION_KEY_BATTERY_STATE_ALGORITHM,
                    )
                ),
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL)),
                vol.Required(
                    CONF_VOLTAGE_OFFSET,
                    default=data.get(CONF_VOLTAGE_OFFSET, DEFAULT_VOLTAGE_OFFSET),
                ): vol.All(vol.Coerce(float)),
                vol.Required(
                    CONF_TEMPERATURE_OFFSET,
                    default=data.get(
                        CONF_TEMPERATURE_OFFSET,
                        DEFAULT_TEMPERATURE_OFFSET,
                    ),
                ): vol.All(vol.Coerce(float)),
                vol.Required(
                    CONF_TEMPERATURE_UNIT,
                    default=data.get(CONF_TEMPERATURE_UNIT, DEFAULT_TEMPERATURE_UNIT),
                ): vol.In(
                    [UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT]
                ),
            }
        )

    elif config_page == ConfigPage.CUSTOM_CALCULATION:
        schema_fields.update(
            {
                vol.Required(
                    CONF_BATTERY_VOLTAGE,
                    default=data.get(
                        CONF_BATTERY_VOLTAGE,
                        DEFAULT_BATTERY_VOLTAGE.value,
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[option.value for option in BatteryVoltage],
                        translation_key=TRANSLATION_KEY_BATTERY_VOLTAGE,
                    )
                ),
                vol.Required(
                    CONF_BATTERY_TYPE,
                    default=data.get(CONF_BATTERY_TYPE, DEFAULT_BATTERY_TYPE.value),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[option.value for option in BatteryType],
                        translation_key=TRANSLATION_KEY_BATTERY_TYPE,
                    )
                ),
            }
        )

    elif config_page == ConfigPage.CUSTOM_VOLTAGE:
        default_range = battery_voltage_ranges.get(
            (
                BatteryType(data.get(CONF_BATTERY_TYPE, DEFAULT_BATTERY_TYPE.value)),
                BatteryVoltage(
                    data.get(CONF_BATTERY_VOLTAGE, DEFAULT_BATTERY_VOLTAGE.value)
                ),
            ),
            battery_voltage_ranges[(DEFAULT_BATTERY_TYPE, DEFAULT_BATTERY_VOLTAGE)],
        )
        schema_fields.update(
            {
                vol.Required(
                    CONF_CUSTOM_DVR_MIN,
                    default=data.get(CONF_CUSTOM_DVR_MIN, default_range.dvr.min),
                ): vol.All(vol.Coerce(float)),
                vol.Required(
                    CONF_CUSTOM_DVR_MAX,
                    default=data.get(CONF_CUSTOM_DVR_MAX, default_range.dvr.max),
                ): vol.All(vol.Coerce(float)),
                vol.Required(
                    CONF_CUSTOM_CVR_MIN,
                    default=data.get(CONF_CUSTOM_CVR_MIN, default_range.cvr.min),
                ): vol.All(vol.Coerce(float)),
                vol.Required(
                    CONF_CUSTOM_CVR_MAX,
                    default=data.get(CONF_CUSTOM_CVR_MAX, default_range.cvr.max),
                ): vol.All(vol.Coerce(float)),
                vol.Required(
                    CONF_CUSTOM_SOD_MIN,
                    default=data.get(CONF_CUSTOM_SOD_MIN, default_range.sod.min),
                ): vol.All(vol.Coerce(float)),
                vol.Required(
                    CONF_CUSTOM_SOD_MAX,
                    default=data.get(CONF_CUSTOM_SOD_MAX, default_range.sod.max),
                ): vol.All(vol.Coerce(float)),
                vol.Required(
                    CONF_CUSTOM_SOC_MIN,
                    default=data.get(CONF_CUSTOM_SOC_MIN, default_range.soc.min),
                ): vol.All(vol.Coerce(float)),
                vol.Required(
                    CONF_CUSTOM_SOC_MAX,
                    default=data.get(CONF_CUSTOM_SOC_MAX, default_range.soc.max),
                ): vol.All(vol.Coerce(float)),
            }
        )

    return vol.Schema(schema_fields)


def validate_custom_voltage(
    data: dict[str, Any], errors: dict[str, str]
) -> dict[str, str]:
    """Validate custom voltage settings."""
    battery_info = Battery.config_to_battery_info(data)
    if battery_info.type == BatteryType.Custom:
        if not battery_info.custom.dvr.is_valid:
            errors[CONF_CUSTOM_DVR_MAX] = ERROR_MAX_LESS_THAN_MIN
        if not battery_info.custom.cvr.is_valid:
            errors[CONF_CUSTOM_CVR_MAX] = ERROR_MAX_LESS_THAN_MIN
        if not battery_info.custom.sod.is_valid:
            errors[CONF_CUSTOM_SOD_MAX] = ERROR_MAX_LESS_THAN_MIN
        if not battery_info.custom.soc.is_valid:
            errors[CONF_CUSTOM_SOC_MAX] = ERROR_MAX_LESS_THAN_MIN
        if not battery_info.custom.is_dvr_less_cvr:
            errors[CONF_CUSTOM_DVR_MAX] = ERROR_CVR_LESS_THAN_DVR
        if not battery_info.custom.is_sod_less_soc:
            errors[CONF_CUSTOM_SOD_MAX] = ERROR_SOC_LESS_THAN_SOD
    return errors


class BM6ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BM6."""

    VERSION = 1

    def __init__(self) -> None:
        self._bluetooth_config: list[dict[str, Any]] | None = None
        self._data: dict[str, Any] = {}

    def _get_name(self, service_info: BluetoothServiceInfoBleak) -> str:
        """Get the name of the device."""
        if service_info.name:
            return f"{service_info.name} {service_info.address}"
        return f"BM6 {service_info.address}"

    async def bluetooth_config(self) -> list[dict[str, Any]]:
        """Return Bluetooth matchers declared in the integration manifest."""
        if self._bluetooth_config is not None:
            return self._bluetooth_config

        try:
            integration = await async_get_integration(self.hass, DOMAIN)
            self._bluetooth_config = integration.manifest.get("bluetooth", [])
        except Exception:
            _LOGGER.exception("Unexpected error loading Bluetooth configuration")
            raise
        return self._bluetooth_config

    async def _get_devices(self) -> dict[str, Any]:
        """Get valid BM6 devices discovered by Home Assistant Bluetooth."""
        bluetooth_config = await self.bluetooth_config()
        devices: dict[str, Any] = {}
        current_addresses = self._async_current_ids()
        all_devices: list[str] = []
        valid_devices: list[str] = []

        for connectable in sorted(
            {item["connectable"] for item in bluetooth_config}
        ):
            for service_info in async_discovered_service_info(
                self.hass,
                connectable=connectable,
            ):
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    all_devices.append(self.format_device_info(service_info))
                if (
                    service_info.address in current_addresses
                    or service_info.address in devices
                ):
                    continue
                if await self._is_valid_device(service_info):
                    devices[service_info.address] = self._get_name(service_info)
                    valid_devices.append(self.format_device_info(service_info))

        _LOGGER.debug("All Bluetooth devices:%s", "".join(all_devices))
        _LOGGER.info("BM6 Bluetooth devices:%s", "".join(valid_devices))
        return devices

    async def _is_valid_device(
        self,
        service_info: BluetoothServiceInfoBleak,
    ) -> bool:
        """Check whether a discovered device matches the BM6 manifest."""
        bluetooth_config = await self.bluetooth_config()
        return any(
            any(item.get("service_uuid") == uuid for item in bluetooth_config)
            for uuid in service_info.service_uuids
        ) or any(
            item.get("manufacturer_id")
            and item.get("manufacturer_data_start")
            and service_info.manufacturer_data.get(item.get("manufacturer_id"))
            and bytes(item["manufacturer_data_start"])
            == service_info.manufacturer_data.get(item.get("manufacturer_id"))[
                : len(item["manufacturer_data_start"])
            ]
            for item in bluetooth_config
        )

    @staticmethod
    def format_device_info(service_info: BluetoothServiceInfoBleak) -> str:
        """Format discovered Bluetooth information for logging."""
        return (
            f"\nMAC:{service_info.address} Name:'{service_info.name}'\n"
            f"\tUUID:{','.join(f'({uuid})' for uuid in service_info.service_uuids)}\n"
            f"\tManufacturer:{','.join(f'({item})' for item in service_info.manufacturer_data.items())}\n"
            f"\tData:{','.join(f'({item})' for item in service_info.service_data.items())}\n"
        )

    async def async_step_bluetooth(
        self,
        discovery_info: BluetoothServiceInfoBleak,
    ) -> FlowResult:
        """Handle Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {
            "name": self._get_name(discovery_info)
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Confirm a discovered BM6 and show the configuration form."""
        self._set_confirm_only()
        devices = {
            self.context["unique_id"]: self.context["title_placeholders"]["name"]
        }
        schema = await build_schema(
            self.hass,
            self._data,
            devices,
            is_options_flow=False,
            config_page=ConfigPage.MAIN,
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the initial configuration step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            device_address = user_input[CONF_DEVICE_ADDRESS]
            await self.async_set_unique_id(device_address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            if (
                BatteryStateAlgorithm(user_input[CONF_STATE_ALGORITHM])
                != BatteryStateAlgorithm.By_Device
            ):
                return await self.async_step_custom_calculation()
            return self.async_create_entry(
                title=f"BM6 {device_address}",
                description="BM6 battery monitor",
                data=self._data,
            )

        if self.context.get("unique_id"):
            self._data[CONF_DEVICE_ADDRESS] = self.context["unique_id"]
            devices = {
                self.context["unique_id"]: self.context["title_placeholders"]["name"]
            }
        else:
            devices = await self._get_devices()
            if not devices:
                return self.async_abort(reason="no_devices_found")

        schema = await build_schema(
            self.hass,
            self._data,
            devices,
            is_options_flow=False,
            config_page=ConfigPage.MAIN,
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_custom_calculation(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle custom battery calculation settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            if BatteryType(user_input[CONF_BATTERY_TYPE]) == BatteryType.Custom:
                return await self.async_step_custom_voltage()
            return self.async_create_entry(
                title=f"BM6 {self._data[CONF_DEVICE_ADDRESS]}",
                description="BM6 battery monitor",
                data=self._data,
            )

        schema = await build_schema(
            self.hass,
            self._data,
            devices=None,
            is_options_flow=False,
            config_page=ConfigPage.CUSTOM_CALCULATION,
        )
        return self.async_show_form(
            step_id="custom_calculation",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_custom_voltage(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle custom voltage settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            errors = validate_custom_voltage(self._data, errors)
            if not errors:
                return self.async_create_entry(
                    title=f"BM6 {self._data[CONF_DEVICE_ADDRESS]}",
                    description="BM6 battery monitor",
                    data=self._data,
                )

        schema = await build_schema(
            self.hass,
            self._data,
            devices=None,
            is_options_flow=False,
            config_page=ConfigPage.CUSTOM_VOLTAGE,
        )
        return self.async_show_form(
            step_id="custom_voltage",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> BM6OptionsFlow:
        """Get the options flow for this handler."""
        return BM6OptionsFlow(config_entry)


class BM6OptionsFlow(OptionsFlow):
    """Handle BM6 options."""

    VERSION = 1

    def __init__(self, config_entry: BM6ConfigEntry) -> None:
        self._config_entry = config_entry
        self._data: dict[str, Any] = dict(config_entry.data)

    async def async_step_user(self, _user_input: dict[str, Any] | None = None):
        """Open the options flow."""
        return await self.async_step_init()

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the main options step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            if (
                BatteryStateAlgorithm(user_input[CONF_STATE_ALGORITHM])
                != BatteryStateAlgorithm.By_Device
            ):
                return await self.async_step_custom_calculation()
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data=self._data,
            )
            return self.async_create_entry(
                title=f"BM6 {self._data[CONF_DEVICE_ADDRESS]}",
                description="BM6 battery monitor",
                data=self._data,
            )

        schema = await build_schema(
            self.hass,
            self._data,
            devices=None,
            is_options_flow=True,
            config_page=ConfigPage.MAIN,
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_custom_calculation(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle custom battery calculation options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            if BatteryType(user_input[CONF_BATTERY_TYPE]) == BatteryType.Custom:
                return await self.async_step_custom_voltage()
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data=self._data,
            )
            return self.async_create_entry(
                title=f"BM6 {self._data[CONF_DEVICE_ADDRESS]}",
                description="BM6 battery monitor",
                data=self._data,
            )

        schema = await build_schema(
            self.hass,
            self._data,
            devices=None,
            is_options_flow=True,
            config_page=ConfigPage.CUSTOM_CALCULATION,
        )
        return self.async_show_form(
            step_id="custom_calculation",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_custom_voltage(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle custom voltage options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            errors = validate_custom_voltage(self._data, errors)
            if not errors:
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=self._data,
                )
                return self.async_create_entry(
                    title=f"BM6 {self._data[CONF_DEVICE_ADDRESS]}",
                    description="BM6 battery monitor",
                    data=self._data,
                )

        schema = await build_schema(
            self.hass,
            self._data,
            devices=None,
            is_options_flow=True,
            config_page=ConfigPage.CUSTOM_VOLTAGE,
        )
        return self.async_show_form(
            step_id="custom_voltage",
            data_schema=schema,
            errors=errors,
        )
