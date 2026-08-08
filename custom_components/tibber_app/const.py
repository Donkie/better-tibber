"""Constants for the Better Tibber integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "tibber_app"

# --- endpoints -------------------------------------------------------------
LOGIN_URL = "https://app.tibber.com/login.credentials"
GQL_URL = "https://app.tibber.com/v4/gql"
WS_URL = "wss://app.tibber.com/v4/gql/ws"
USER_AGENT = "Tibber/24.10.0 (Android)"

# --- config entry data keys ------------------------------------------------
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_TOKEN = "token"
CONF_REFRESH_TOKEN = "refresh_token"

# --- polling ---------------------------------------------------------------
SCAN_INTERVAL = timedelta(seconds=60)

# --- gizmo / device types (from me.home.gizmos[].type) ---------------------
GIZMO_ELECTRIC_VEHICLE = "ELECTRIC_VEHICLE"
GIZMO_EV_CHARGER = "EV_CHARGER"
GIZMO_REAL_TIME_METER = "REAL_TIME_METER"
GIZMO_BATTERY = "BATTERY"
GIZMO_INVERTER = "INVERTER"
GIZMO_THERMOSTAT = "THERMOSTAT"

# Manufacturer label used for HA device registry entries.
MANUFACTURER = "Tibber"

# --- magic values ----------------------------------------------------------
# Charger preferredVehicleId sentinel meaning "Auto" (let Tibber pick).
PREFERRED_VEHICLE_AUTO = "00000000-0000-0000-0000-000000000000"

# Vehicle setting key for the manual state-of-charge override.
VEHICLE_SOC_KEY = "offline.vehicle.batteryLevel"

# Vehicle smart-charging setting keys (read/written via setVehicleSettings).
VEHICLE_SMART_CHARGING_KEY = "offline.vehicle.smartCharging.isEnabled"
# Weekly departure schedule: one "HH:MM" string per weekday.
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
VEHICLE_DEPARTURE_KEY = "offline.vehicle.departureTimes.{day}"

# Battery operation modes (HomeBatteryOperationMode enum).
BATTERY_MODES = ["BASIC", "SMART_EARNINGS", "SMART_SELF_CONSUMPTION"]
