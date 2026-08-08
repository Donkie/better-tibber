"""Sensor platform for the Tibber app integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TibberConfigEntry
from .const import (
    GIZMO_BATTERY,
    GIZMO_ELECTRIC_VEHICLE,
    GIZMO_EV_CHARGER,
    GIZMO_INVERTER,
    GIZMO_REAL_TIME_METER,
)
from .coordinator import TibberDataUpdateCoordinator, TibberDevice
from .entity import TibberEntity, TibberHomeEntity


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    return dt_util.parse_datetime(value)


# When a vehicle has no upcoming departure (no schedule for the day, or the last
# one already passed) the API echoes back the current server time instead of
# null, which makes the sensor tick once per poll forever. Treat any value that
# is not comfortably in the future as "no target departure".
DEPARTURE_PAST_TOLERANCE = timedelta(minutes=2)


def _parse_departure(value: Any) -> datetime | None:
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    aware = parsed if parsed.tzinfo else dt_util.as_local(parsed)
    if aware <= dt_util.utcnow() + DEPARTURE_PAST_TOLERANCE:
        return None
    return parsed


# --- description dataclasses ------------------------------------------------
@dataclass(frozen=True, kw_only=True)
class TibberSensorDescription(SensorEntityDescription):
    """Sensor description with a value extractor over a device node dict."""

    value_fn: Callable[[dict[str, Any]], Any]
    # Optional dynamic unit (e.g. currency that the API reports per measurement).
    unit_fn: Callable[[dict[str, Any]], str | None] | None = None


VEHICLE_SENSORS: tuple[TibberSensorDescription, ...] = (
    TibberSensorDescription(
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: (v.get("battery") or {}).get("level"),
    ),
    TibberSensorDescription(
        key="range",
        translation_key="range",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        value_fn=lambda v: (v.get("battery") or {}).get("estimatedRange"),
    ),
    TibberSensorDescription(
        key="charging_status",
        translation_key="charging_status",
        device_class=SensorDeviceClass.ENUM,
        value_fn=lambda v: v.get("chargingStatus"),
    ),
    TibberSensorDescription(
        key="smart_charging_status",
        translation_key="smart_charging_status",
        device_class=SensorDeviceClass.ENUM,
        value_fn=lambda v: v.get("smartChargingStatus"),
    ),
    TibberSensorDescription(
        key="session_energy",
        translation_key="session_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        # The app's live estimate can tick down slightly mid-session (not just
        # reset to 0 at session start), so it isn't strictly increasing.
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda v: ((v.get("charging") or {}).get("summary") or {}).get(
            "energyConsumed"
        ),
    ),
    TibberSensorDescription(
        key="target_soc",
        translation_key="target_soc",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda v: (v.get("charging") or {}).get("targetedStateOfCharge"),
    ),
    TibberSensorDescription(
        key="target_departure",
        translation_key="target_departure",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda v: _parse_departure(
            (v.get("charging") or {}).get("targetedDepartureTime")
        ),
    ),
)

CHARGER_SENSORS: tuple[TibberSensorDescription, ...] = (
    TibberSensorDescription(
        key="charging_status",
        translation_key="charging_status",
        device_class=SensorDeviceClass.ENUM,
        value_fn=lambda v: v.get("chargingStatus"),
    ),
    TibberSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda v: _parse_dt(v.get("lastSeen")),
    ),
    TibberSensorDescription(
        key="active_vehicle",
        translation_key="active_vehicle",
        value_fn=lambda v: next(
            (x.get("name") for x in (v.get("vehicles") or []) if x.get("isPreferred")),
            None,
        ),
    ),
)

# Pulse live sensors read from coordinator.data.live[pulse_id].
PULSE_SENSORS: tuple[TibberSensorDescription, ...] = (
    TibberSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: v.get("power"),
    ),
    TibberSensorDescription(
        key="power_production",
        translation_key="power_production",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: v.get("powerProduction"),
    ),
    TibberSensorDescription(
        key="accumulated_consumption",
        translation_key="accumulated_consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda v: v.get("accumulatedConsumption"),
    ),
    TibberSensorDescription(
        key="accumulated_production",
        translation_key="accumulated_production",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda v: v.get("accumulatedProduction"),
    ),
    TibberSensorDescription(
        key="accumulated_cost",
        translation_key="accumulated_cost",
        device_class=SensorDeviceClass.MONETARY,
        # MONETARY disallows total_increasing; use total (it resets at midnight).
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda v: v.get("accumulatedCost"),
        unit_fn=lambda v: v.get("currency"),
    ),
    TibberSensorDescription(
        key="current_l1",
        translation_key="current_l1",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda v: v.get("currentPhase1"),
    ),
    TibberSensorDescription(
        key="current_l2",
        translation_key="current_l2",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda v: v.get("currentPhase2"),
    ),
    TibberSensorDescription(
        key="current_l3",
        translation_key="current_l3",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda v: v.get("currentPhase3"),
    ),
    TibberSensorDescription(
        key="voltage_l1",
        translation_key="voltage_l1",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda v: v.get("voltagePhase1"),
    ),
    TibberSensorDescription(
        key="voltage_l2",
        translation_key="voltage_l2",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda v: v.get("voltagePhase2"),
    ),
    TibberSensorDescription(
        key="voltage_l3",
        translation_key="voltage_l3",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda v: v.get("voltagePhase3"),
    ),
    TibberSensorDescription(
        key="signal_strength",
        translation_key="signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda v: v.get("signalStrength"),
    ),
)

INVERTER_SENSORS: tuple[TibberSensorDescription, ...] = (
    TibberSensorDescription(
        key="production_now",
        translation_key="production_now",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: (v.get("bubble") or {}).get("value"),
    ),
)

BATTERY_SENSORS: tuple[TibberSensorDescription, ...] = (
    TibberSensorDescription(
        key="operation_mode",
        translation_key="operation_mode",
        device_class=SensorDeviceClass.ENUM,
        value_fn=lambda v: (v.get("currentOperationMode") or {}).get("value"),
    ),
)

# Live battery sensors read from coordinator.data.battery_live[battery_id].
BATTERY_LIVE_SENSORS: tuple[TibberSensorDescription, ...] = (
    TibberSensorDescription(
        key="state_of_charge",
        translation_key="state_of_charge",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: v.get("stateOfCharge"),
    ),
    TibberSensorDescription(
        key="status",
        translation_key="battery_status",
        device_class=SensorDeviceClass.ENUM,
        value_fn=lambda v: v.get("status"),
    ),
    TibberSensorDescription(
        key="power_from_solar",
        translation_key="power_from_solar",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: v.get("powerFromSolar"),
    ),
    TibberSensorDescription(
        key="power_from_grid",
        translation_key="power_from_grid",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: v.get("powerFromGrid"),
    ),
    TibberSensorDescription(
        key="power_to_home",
        translation_key="power_to_home",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: v.get("powerToHome"),
    ),
    TibberSensorDescription(
        key="power_to_grid",
        translation_key="power_to_grid",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: v.get("powerToGrid"),
    ),
)


PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TibberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tibber app sensors."""
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = []

    for dev in coordinator.devices_of_type(GIZMO_ELECTRIC_VEHICLE):
        entities += [
            TibberDeviceSensor(coordinator, dev, desc, "vehicles")
            for desc in VEHICLE_SENSORS
        ]
        entities.append(TibberVehicleSessionCostSensor(coordinator, dev))
    for dev in coordinator.devices_of_type(GIZMO_EV_CHARGER):
        entities += [
            TibberDeviceSensor(coordinator, dev, desc, "chargers")
            for desc in CHARGER_SENSORS
        ]
    for dev in coordinator.devices_of_type(GIZMO_REAL_TIME_METER):
        entities += [
            TibberPulseSensor(coordinator, dev, desc) for desc in PULSE_SENSORS
        ]
    for dev in coordinator.devices_of_type(GIZMO_INVERTER):
        entities += [
            TibberDeviceSensor(coordinator, dev, desc, "inverters")
            for desc in INVERTER_SENSORS
        ]
        entities.append(TibberInverterProductionTodaySensor(coordinator, dev))
    for dev in coordinator.devices_of_type(GIZMO_BATTERY):
        entities += [
            TibberDeviceSensor(coordinator, dev, desc, "batteries")
            for desc in BATTERY_SENSORS
        ]
        entities += [
            TibberBatteryLiveSensor(coordinator, dev, desc)
            for desc in BATTERY_LIVE_SENSORS
        ]

    # Home-level price + consumption sensors.
    for home_id in coordinator.home_titles:
        entities += [
            TibberPriceSensor(coordinator, home_id),
            TibberConsumptionTodaySensor(coordinator, home_id),
            TibberCostTodaySensor(coordinator, home_id),
        ]
        # Only add Grid Rewards where the home actually reports it.
        if (coordinator.data.homes.get(home_id) or {}).get("gridRewards"):
            entities.append(TibberGridRewardsSensor(coordinator, home_id))

    async_add_entities(entities)


class TibberDeviceSensor(TibberEntity, SensorEntity):
    """Sensor backed by a device node in a coordinator collection."""

    entity_description: TibberSensorDescription

    def __init__(
        self,
        coordinator: TibberDataUpdateCoordinator,
        device: TibberDevice,
        description: TibberSensorDescription,
        collection: str,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description
        self._collection = collection

    @property
    def native_value(self) -> Any:
        node = getattr(self.coordinator.data, self._collection).get(self._device.id)
        if node is None:
            return None
        return self.entity_description.value_fn(node)


class TibberPulseSensor(TibberEntity, SensorEntity):
    """Live Pulse sensor reading from coordinator.data.live."""

    entity_description: TibberSensorDescription

    def __init__(
        self,
        coordinator: TibberDataUpdateCoordinator,
        device: TibberDevice,
        description: TibberSensorDescription,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        node = self.coordinator.data.live.get(self._device.id)
        if node is None:
            return None
        return self.entity_description.value_fn(node)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.unit_fn:
            node = self.coordinator.data.live.get(self._device.id) or {}
            return self.entity_description.unit_fn(node)
        return self.entity_description.native_unit_of_measurement


class TibberBatteryLiveSensor(TibberEntity, SensorEntity):
    """Live battery sensor reading from coordinator.data.battery_live (WebSocket)."""

    entity_description: TibberSensorDescription

    def __init__(
        self,
        coordinator: TibberDataUpdateCoordinator,
        device: TibberDevice,
        description: TibberSensorDescription,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        node = self.coordinator.data.battery_live.get(self._device.id)
        if node is None:
            return None
        return self.entity_description.value_fn(node)


class TibberVehicleSessionCostSensor(TibberEntity, SensorEntity):
    """Cost of the current/last charging session (currency from the home)."""

    _attr_translation_key = "session_cost"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self, coordinator: TibberDataUpdateCoordinator, device: TibberDevice
    ) -> None:
        super().__init__(coordinator, device, "session_cost")

    @property
    def native_value(self) -> Any:
        node = self.coordinator.data.vehicles.get(self._device.id) or {}
        return ((node.get("charging") or {}).get("summary") or {}).get("total")

    @property
    def native_unit_of_measurement(self) -> str | None:
        # The vehicle summary has no currency; borrow it from the home's prices.
        home = self.coordinator.data.homes.get(self._device.home_id) or {}
        return ((home.get("price") or {}).get("hourly") or {}).get("currency")


class TibberInverterProductionTodaySensor(TibberEntity, SensorEntity):
    """Solar production so far today (summed from the inverter production query)."""

    _attr_translation_key = "production_today"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self, coordinator: TibberDataUpdateCoordinator, device: TibberDevice
    ) -> None:
        super().__init__(coordinator, device, "production_today")

    @property
    def native_value(self) -> Any:
        prod = self.coordinator.data.inverter_production.get(self._device.id)
        if not prod:
            return None
        items = prod.get("items") or []
        values = [i.get("value") for i in items if i.get("value") is not None]
        return round(sum(values), 3) if values else None


def _current_price_entry(price: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the hourly price entry covering the current hour."""
    if not price:
        return None
    hourly = price.get("hourly") or {}
    entries = hourly.get("entries") or []
    now = dt_util.now()
    current = None
    for entry in entries:
        ts = dt_util.parse_datetime(entry.get("time", ""))
        if ts and ts <= now:
            current = entry
    return current


class TibberPriceSensor(TibberHomeEntity, SensorEntity):
    """Current total electricity price (a rate), with today/tomorrow as attributes."""

    _attr_translation_key = "electricity_price"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: TibberDataUpdateCoordinator, home_id: str) -> None:
        super().__init__(coordinator, home_id, "electricity_price")

    @property
    def native_unit_of_measurement(self) -> str | None:
        # Price is a rate, so the unit is currency per kWh (e.g. SEK/kWh).
        currency = ((self._home.get("price") or {}).get("hourly") or {}).get("currency")
        return f"{currency}/kWh" if currency else None

    @property
    def native_value(self) -> Any:
        entry = _current_price_entry(self._home.get("price"))
        return entry.get("total") if entry else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        price = self._home.get("price") or {}
        entries = (price.get("hourly") or {}).get("entries") or []
        today = dt_util.now().date()
        tomorrow = today + timedelta(days=1)
        by_day: dict[Any, list] = {today: [], tomorrow: []}
        for entry in entries:
            ts = dt_util.parse_datetime(entry.get("time", ""))
            if ts and ts.date() in by_day:
                by_day[ts.date()].append(entry)
        return {
            "energy": (_current_price_entry(price) or {}).get("energy"),
            "today": by_day[today],
            "tomorrow": by_day[tomorrow],
        }


class TibberConsumptionTodaySensor(TibberHomeEntity, SensorEntity):
    """Energy consumed this month (from the consumption gizmo, month-to-date)."""

    _attr_translation_key = "consumption_month"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: TibberDataUpdateCoordinator, home_id: str) -> None:
        super().__init__(coordinator, home_id, "consumption_month")

    @property
    def native_value(self) -> Any:
        return (self._home.get("consumption") or {}).get("consumption")


class TibberCostTodaySensor(TibberHomeEntity, SensorEntity):
    """Energy cost this month (from the consumption gizmo, month-to-date)."""

    _attr_translation_key = "cost_month"
    _attr_device_class = SensorDeviceClass.MONETARY
    # MONETARY disallows total_increasing; use total (it resets each month).
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: TibberDataUpdateCoordinator, home_id: str) -> None:
        super().__init__(coordinator, home_id, "cost_month")

    @property
    def native_unit_of_measurement(self) -> str | None:
        return (self._home.get("consumption") or {}).get("currency")

    @property
    def native_value(self) -> Any:
        return (self._home.get("consumption") or {}).get("cost")


class TibberGridRewardsSensor(TibberHomeEntity, SensorEntity):
    """Grid Rewards earned this month (with vehicle/battery split as attributes)."""

    _attr_translation_key = "grid_rewards_month"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: TibberDataUpdateCoordinator, home_id: str) -> None:
        super().__init__(coordinator, home_id, "grid_rewards_month")

    @property
    def _rewards(self) -> dict[str, Any]:
        return self._home.get("gridRewards") or {}

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._rewards.get("currency")

    @property
    def native_value(self) -> Any:
        return self._rewards.get("totalReward")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "vehicle_rewards": self._rewards.get("vehicleRewards"),
            "battery_rewards": self._rewards.get("batteryRewards"),
        }
