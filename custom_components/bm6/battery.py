"""Battery information, configuration and check routines"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_CUSTOM_DVR_MIN,
    CONF_CUSTOM_DVR_MAX,
    CONF_CUSTOM_CVR_MIN,
    CONF_CUSTOM_CVR_MAX,
    CONF_CUSTOM_SOC_MIN,
    CONF_CUSTOM_SOC_MAX,
    CONF_CUSTOM_SOD_MIN,
    CONF_CUSTOM_SOD_MAX,
    CONF_BATTERY_VOLTAGE,
    CONF_BATTERY_TYPE,
    CONF_STATE_ALGORITHM,
)
from .bm6_connect import BM6RealTimeData, BM6RealTimeState


class BatteryVoltage(Enum):
    """
    Battery voltages type
    Important: This enumerator correspond in 1:1 to translation files in section enums.BatteryVoltage
    """

    V6 = "6V"
    V12 = "12V"


class BatteryType(Enum):
    """
    Battery technology type
    Important: This enumerator correspond in 1:1 to translation files in section enums.BatteryType
    """

    FLA = "fla"  # "Flooded Lead-Acid (FLA)"
    AGM = "agm"  # "Absorbent Glass Mat (AGM)"
    GEL = "gel"  # "Gel Cell (GEL)"
    EFB = "efb"  # "Enhanced Flooded Battery (EFB)"
    NiCd = "nicd"  # "Nickel-Cadmium (NiCd)"
    NiMH = "nimh"  # "Nickel-Metal Hydride (NiMH)"
    LiIon = "liion"  # "Lithium-Ion (Li-Ion)"
    LiFePO4 = "lifepo4"  # "Lithium Iron Phosphate (LiFePO4)"
    LTO = "lto"  # "Lithium Titanate (LTO)"
    Custom = "custom"  # "Custom Battery"


class BatteryStateAlgorithm(Enum):
    """
    Battery state algorithm type - algorithm to calculate the percentage of state of charge or discharge
    """

    By_Device = "by_device"  # Calculated by BM6 Device
    SoC_SoD = "soc_sod"  # Calculated using State of Charge/Discharge
    CVR_DVR = "cvr_dvr"  # Calculated using Charging/Discharging Voltage Range


class BatteryState(Enum):
    """
    Battery states type
    """

    Unknown = "unknown"
    Ok = "ok"
    LowVoltage = "low_voltage"
    UnderVoltage = "under_voltage"
    Discharging = "discharging"
    Idle = "idle"
    Charging = "charging"
    OverVoltage = "over_voltage"


@dataclass
class VoltageRange:
    """Battery voltage ranges"""

    min: float
    max: float

    @property
    def is_valid(self) -> bool:
        return (
            self.min is not None
            and self.max is not None
            and self.min > 0
            and self.max >= self.min
        )

    def calc_percent(self, voltage: float) -> float:
        if voltage is None or not self.is_valid or voltage < self.min:
            return None
        elif voltage > self.max:
            return 100.0
        else:
            return round(((voltage - self.min) / (self.max - self.min)) * 100, 1)

    def in_range(self, voltage: float) -> bool:
        return voltage is not None and self.is_valid and self.min <= voltage <= self.max

    def is_less_than(self, other: "VoltageRange") -> bool:
        return self.is_valid and other.is_valid and self.min < other.min

    def get_diagnostic_data(self) -> dict[str, Any]:
        return {
            "min_voltage": self.min,
            "max_voltage": self.max,
            "is_valid": self.is_valid,
        }


@dataclass
class BatteryRange:
    """Battery states voltage ranges"""

    dvr: VoltageRange
    cvr: VoltageRange
    soc: VoltageRange
    sod: VoltageRange

    @property
    def is_dvr_less_cvr(self) -> bool:
        return self.dvr.is_less_than(self.cvr)

    @property
    def is_sod_less_soc(self) -> bool:
        return self.sod.is_less_than(self.soc)

    @property
    def is_valid(self) -> bool:
        return (
            self.dvr.is_valid
            and self.cvr.is_valid
            and self.soc.is_valid
            and self.sod.is_valid
            and self.is_dvr_less_cvr
            and self.is_sod_less_soc
        )

    def get_diagnostic_data(self) -> dict[str, Any]:
        return {
            "dvr": self.dvr.get_diagnostic_data(),
            "cvr": self.cvr.get_diagnostic_data(),
            "soc": self.soc.get_diagnostic_data(),
            "sod": self.sod.get_diagnostic_data(),
            "is_valid": self.is_valid,
        }


@dataclass
class BatteryInfo:
    """Battery information"""

    voltage: BatteryVoltage
    type: BatteryType
    custom: BatteryRange
    state_algorithm: BatteryStateAlgorithm

    @property
    def is_valid(self) -> bool:
        return (
            self.voltage in BatteryVoltage
            and self.type in BatteryType
            and self.state_algorithm in BatteryStateAlgorithm
            and (self.type != BatteryType.Custom or self.custom.is_valid)
        )

    def get_diagnostic_data(self) -> dict[str, Any]:
        return {
            "voltage": self.voltage.value,
            "type": self.type.value,
            "custom": self.custom.get_diagnostic_data(),
            "state_algorithm": self.state_algorithm.value,
            "is_valid": self.is_valid,
        }


# Dictionary mapping battery types and voltages to their respective ranges
battery_voltage_ranges = {
    (BatteryType.FLA, BatteryVoltage.V6): BatteryRange(
        dvr=VoltageRange(5.8, 6.3),
        cvr=VoltageRange(6.8, 7.2),
        soc=VoltageRange(6.0, 6.3),
        sod=VoltageRange(5.8, 6.0),
    ),
    (BatteryType.FLA, BatteryVoltage.V12): BatteryRange(
        dvr=VoltageRange(10.5, 12.7),
        cvr=VoltageRange(13.2, 15.5),  # Détection de charge plus sensible
        # On utilise une plage unique de 11.6V (0%) à 12.7V (100%)
        soc=VoltageRange(11.6, 12.7),
        sod=VoltageRange(11.6, 12.7),
    ),
    (BatteryType.AGM, BatteryVoltage.V6): BatteryRange(
        dvr=VoltageRange(5.8, 6.3),
        cvr=VoltageRange(6.8, 7.2),
        soc=VoltageRange(6.0, 6.3),
        sod=VoltageRange(5.8, 6.0),
    ),
    (BatteryType.AGM, BatteryVoltage.V12): BatteryRange(
        dvr=VoltageRange(10.5, 12.6),
        cvr=VoltageRange(14.4, 14.7),
        soc=VoltageRange(12.0, 12.6),
        sod=VoltageRange(10.5, 12.0),
    ),
    (BatteryType.GEL, BatteryVoltage.V6): BatteryRange(
        dvr=VoltageRange(5.8, 6.3),
        cvr=VoltageRange(6.8, 7.2),
        soc=VoltageRange(6.0, 6.3),
        sod=VoltageRange(5.8, 6.0),
    ),
    (BatteryType.GEL, BatteryVoltage.V12): BatteryRange(
        dvr=VoltageRange(10.5, 12.6),
        cvr=VoltageRange(13.8, 14.4),
        soc=VoltageRange(12.0, 12.6),
        sod=VoltageRange(10.5, 12.0),
    ),
    # AJOUT EFB 12V
    (BatteryType.EFB, BatteryVoltage.V12): BatteryRange(
        dvr=VoltageRange(10.5, 12.7),
        cvr=VoltageRange(13.2, 15.8),
        # On aligne soc et sod pour que le calcul soit identique au repos
        soc=VoltageRange(11.8, 12.7),
        sod=VoltageRange(11.8, 12.7),
    ),
    (BatteryType.NiCd, BatteryVoltage.V6): BatteryRange(
        dvr=VoltageRange(5.4, 6.0),
        cvr=VoltageRange(6.8, 7.2),
        soc=VoltageRange(5.8, 6.0),
        sod=VoltageRange(5.4, 5.8),
    ),
    (BatteryType.NiCd, BatteryVoltage.V12): BatteryRange(
        dvr=VoltageRange(10.8, 12.0),
        cvr=VoltageRange(13.6, 14.4),
        soc=VoltageRange(11.5, 12.0),
        sod=VoltageRange(10.8, 11.5),
    ),
    (BatteryType.NiMH, BatteryVoltage.V6): BatteryRange(
        dvr=VoltageRange(5.4, 6.0),
        cvr=VoltageRange(6.8, 7.2),
        soc=VoltageRange(5.8, 6.0),
        sod=VoltageRange(5.4, 5.8),
    ),
    (BatteryType.NiMH, BatteryVoltage.V12): BatteryRange(
        dvr=VoltageRange(10.8, 12.0),
        cvr=VoltageRange(13.6, 14.4),
        soc=VoltageRange(11.5, 12.0),
        sod=VoltageRange(10.8, 11.5),
    ),
    (BatteryType.LiIon, BatteryVoltage.V6): BatteryRange(
        dvr=VoltageRange(6.0, 7.2),
        cvr=VoltageRange(7.0, 7.2),
        soc=VoltageRange(6.5, 7.2),
        sod=VoltageRange(6.0, 6.5),
    ),
    (BatteryType.LiIon, BatteryVoltage.V12): BatteryRange(
        dvr=VoltageRange(10.0, 13.5),
        cvr=VoltageRange(14.4, 14.6),
        soc=VoltageRange(12.0, 13.5),
        sod=VoltageRange(10.0, 12.0),
    ),
    (BatteryType.LiFePO4, BatteryVoltage.V12): BatteryRange(
        dvr=VoltageRange(12.0, 13.5),
        cvr=VoltageRange(14.6, 15.0),
        soc=VoltageRange(13.0, 13.5),
        sod=VoltageRange(12.0, 13.0),
    ),
    (BatteryType.LTO, BatteryVoltage.V6): BatteryRange(
        dvr=VoltageRange(5.4, 6.6),
        cvr=VoltageRange(6.0, 6.6),
        soc=VoltageRange(6.0, 6.6),
        sod=VoltageRange(5.4, 6.0),
    ),
    (BatteryType.LTO, BatteryVoltage.V12): BatteryRange(
        dvr=VoltageRange(10.8, 13.2),
        cvr=VoltageRange(12.0, 13.2),
        soc=VoltageRange(12.0, 13.2),
        sod=VoltageRange(10.8, 12.0),
    ),
}


class Battery:
    """Battery class representing state and charge percentage"""

    def __init__(self, config_dict: dict[str, Any]):
        self.info: BatteryInfo = self.config_to_battery_info(config_dict)
        self._voltage: float = 0.0
        self._state: BatteryState = BatteryState.Idle
        self._percent: int = 0

    @property
    def voltage(self) -> float:
        return self._voltage

    @voltage.setter
    def voltage(self, value: float):
        self._voltage = value
        self._update_state()
        self._update_percent()

    @property
    def state(self) -> BatteryState:
        return self._state

    @property
    def percent(self) -> int:
        return self._percent

    @property
    def range(self) -> BatteryRange:
        if self.info.type == BatteryType.Custom:
            return self.info.custom
        else:
            return battery_voltage_ranges[(self.info.type, self.info.voltage)]

    @property
    def soc(self) -> float:
        return self.range.soc.calc_percent(self._voltage)

    @property
    def sod(self) -> float:
        return self.range.sod.calc_percent(self._voltage)

    @property
    def cvr(self) -> float:
        return self.range.cvr.calc_percent(self._voltage)

    @property
    def dvr(self) -> float:
        return self.range.dvr.calc_percent(self._voltage)

    @property
    def is_dvr(self) -> bool:
        return self.range.dvr.in_range(self._voltage)

    @property
    def is_cvr(self) -> bool:
        return self.range.cvr.in_range(self._voltage)

    @property
    def is_soc(self) -> bool:
        return self.range.soc.in_range(self._voltage)

    @property
    def is_sod(self) -> bool:
        return self.range.sod.in_range(self._voltage)

    def update(self, real_time_data: BM6RealTimeData, voltage: float):
        self._voltage = voltage
        if self.info.state_algorithm == BatteryStateAlgorithm.By_Device:
            self._percent = real_time_data.Percent
            self._state = self._bm6_status_to_battery_state(real_time_data.State)
        else:
            self._update_percent()
            self._update_state()

    def _update_state(self):
        if self.info.state_algorithm == BatteryStateAlgorithm.By_Device:
            return
        if self._voltage is None:
            self._state = None
            return
        if self._voltage < self.range.dvr.min:
            self._state = BatteryState.UnderVoltage
        elif self._voltage > self.range.cvr.max:
            self._state = BatteryState.OverVoltage
        elif (self.info.state_algorithm == BatteryStateAlgorithm.SoC_SoD and self.is_sod) or (
            self.info.state_algorithm == BatteryStateAlgorithm.CVR_DVR and self.is_dvr
        ):
            self._state = BatteryState.Discharging
        elif (self.info.state_algorithm == BatteryStateAlgorithm.SoC_SoD and self.is_soc) or (
            self.info.state_algorithm == BatteryStateAlgorithm.CVR_DVR and self.is_cvr
        ):
            self._state = BatteryState.Charging
        else:
            self._state = BatteryState.Idle

    def _bm6_status_to_battery_state(self, state: Any) -> BatteryState:
        """Map the raw BM6 device status to a BatteryState.

        ``state`` comes from ``BM6RealTimeData.State`` and is a plain ``int``
        parsed from the BLE payload, while the keys of ``state_mapping`` are
        members of ``BM6RealTimeState`` (a plain ``Enum``, NOT an
        ``IntEnum``). A plain Enum member never compares equal to (or hashes
        like) a raw int, so ``state_mapping.get(<int>, default)`` would never
        match and would always silently fall back to ``BatteryState.Unknown``.

        We therefore first normalize ``state`` into a ``BM6RealTimeState``
        member (this also works fine if ``state`` is already such a member)
        before doing the lookup. Unknown/unsupported status codes fall back
        to ``BatteryState.Unknown``.
        """
        state_mapping = {
            BM6RealTimeState.BatteryOk: BatteryState.Ok,
            BM6RealTimeState.LowVoltage: BatteryState.LowVoltage,
            BM6RealTimeState.Charging: BatteryState.Charging,
        }
        try:
            bm6_state = BM6RealTimeState(state)
        except ValueError:
            return BatteryState.Unknown
        return state_mapping.get(bm6_state, BatteryState.Unknown)

    def _update_percent(self):
        if self.info.state_algorithm == BatteryStateAlgorithm.By_Device:
            return
        elif self.info.state_algorithm == BatteryStateAlgorithm.SoC_SoD:
            if self.is_soc:
                self._percent = self.soc
            elif self.is_sod:
                self._percent = self.sod
            elif self.state == BatteryState.Idle:
                self._percent = 100
            else:
                self._percent = 0
        elif self.info.state_algorithm == BatteryStateAlgorithm.CVR_DVR:
            if self.is_cvr:
                self._percent = self.cvr
            elif self.is_dvr:
                self._percent = self.dvr
            elif self.state == BatteryState.Idle:
                self._percent = 100
            else:
                self._percent = 0
        else:
            self._percent = 0

    def get_diagnostic_data(self) -> dict[str, Any]:
        return {
            "voltage": self.voltage,
            "state": self.state.value,
            "percent": self.percent,
            "info": self.info.get_diagnostic_data(),
        }

    @staticmethod
    def config_to_battery_info(config_dict: dict[str, Any]) -> BatteryInfo:
        voltage = config_dict.get(CONF_BATTERY_VOLTAGE)
        battery_type = config_dict.get(CONF_BATTERY_TYPE)
        state_algorithm = config_dict.get(CONF_STATE_ALGORITHM)

        if voltage not in BatteryVoltage._value2member_map_:
            raise ValueError(f"Invalid battery voltage: {voltage}")
        if battery_type not in BatteryType._value2member_map_:
            raise ValueError(f"Invalid battery type: {battery_type}")
        if state_algorithm not in BatteryStateAlgorithm._value2member_map_:
            raise ValueError(f"Invalid battery algorithm: {state_algorithm}")

        return BatteryInfo(
            voltage=BatteryVoltage(voltage),
            type=BatteryType(battery_type),
            custom=BatteryRange(
                dvr=VoltageRange(config_dict.get(CONF_CUSTOM_DVR_MIN), config_dict.get(CONF_CUSTOM_DVR_MAX)),
                cvr=VoltageRange(config_dict.get(CONF_CUSTOM_CVR_MIN), config_dict.get(CONF_CUSTOM_CVR_MAX)),
                soc=VoltageRange(config_dict.get(CONF_CUSTOM_SOC_MIN), config_dict.get(CONF_CUSTOM_SOC_MAX)),
                sod=VoltageRange(config_dict.get(CONF_CUSTOM_SOD_MIN), config_dict.get(CONF_CUSTOM_SOD_MAX)),
            ),
            state_algorithm=BatteryStateAlgorithm(state_algorithm),
        )

    @staticmethod
    def percent_to_icon(percent: int) -> str:
        if percent is None:
            return "mdi:battery"
        levels = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        icons = ["mdi:battery-outline", "mdi:battery-10", "mdi:battery-20", "mdi:battery-30",
                 "mdi:battery-40", "mdi:battery-50", "mdi:battery-60", "mdi:battery-70",
                 "mdi:battery-80", "mdi:battery-90", "mdi:battery"]
        for i, level in enumerate(levels):
            if percent < level:
                return icons[i]
        return "mdi:battery"
