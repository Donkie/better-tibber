# Tibber app (unofficial) — Home Assistant integration

A custom component that exposes the **Tibber mobile app** GraphQL API
(`app.tibber.com`) as native Home Assistant entities — EV/charger control, a live
real-time meter, prices, and (where present) battery, solar and thermostats.

> ⚠️ **Unofficial.** Not endorsed by Tibber; the API may change or break without
> notice. Use your own account and respect the rate limit.

## Installation

1. Copy `custom_components/tibber_app/` into your Home Assistant `config/custom_components/`.
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → "Tibber (unofficial app API)"**.
4. Enter your Tibber app email + password. The integration logs in, stores the
   token, and auto-discovers your homes and devices.

## How it works

- **One config entry per account.** Each home becomes an HA device; each physical
  device (vehicle, charger, Pulse, battery, inverter, thermostat) becomes its own
  device, linked to its home.
- **Polling** (every 60 s) issues *one combined GraphQL query per home* — the
  per-device sub-selections are aliased into a single request to stay well under
  the API's ~20 req/s limit.
- **Live meter** data (`liveMeasurement`) arrives over WebSocket
  (`wss://app.tibber.com/v4/gql/ws`) and updates the Pulse sensors in near real
  time. The socket is best-effort and reconnects on drop; polling stays the source
  of truth.

## Entities

| Device | Entities |
|---|---|
| **Vehicle** | battery %, range, charging/smart-charging status, session energy, session cost, target charge/departure · online + charging binary sensors · **manual state-of-charge number** · **smart-charging switch** · **weekly departure schedule** (see below) |
| **Charger** | charging status, last seen, active vehicle · online binary sensor · **preferred-vehicle select** · permanent-cable-lock & fuse-load-balancing switches · max-current / main-fuse / offline-fallback numbers |
| **Pulse (live)** | power, production, phase currents/voltages, consumption/production/cost today, signal · online* / peak-exceeded binary sensors |
| **Home** | electricity price (+ today/tomorrow arrays), consumption & cost this month · Grid Rewards this month (where available) · **hourly forecast `weather` entity** · away-mode / peak-control switches · peak-limit number · refresh button |
| **Battery** | state of charge, status, power from solar/grid, power to home/grid (live via WebSocket) · operation-mode sensor + **select** · Grid Rewards enabled |
| **Inverter** | current production · production today |
| **Thermostat** | full `climate` entity (mode, target/current temp, on/off) |

### Weekly smart-charging schedule

Tibber's smart charging stores a **per-weekday departure time** plus a master
on/off, all as vehicle user settings (`offline.vehicle.smartCharging.isEnabled`
and `offline.vehicle.departureTimes.<weekday>`). These are exposed as real,
read-write entities on each vehicle:

- **Smart charging** — a `switch` reflecting the actual `isEnabled` flag (not
  optimistic — it reads the stored value back).
- **Departure Monday … Departure Sunday** — seven `time` entities, one per weekday.
  Setting one writes `"HH:MM"` back via `setVehicleSettings`.

So the weekly schedule is just the seven `time.<vehicle>_departure_<weekday>`
entities; automate or adjust them like any other HA time helper. (Target
state-of-charge is reported by the *Target charge* sensor; the app exposes no
writable per-day SoC setting, only the departure times.)

\* Phase voltages/currents and signal strength are disabled by default — enable
them per entity if you want them.

## Known limitations

- **No start/stop charging.** The app API exposes no explicit start/stop-charge
  mutation, so charging is controlled via the preferred-vehicle selector, the
  charger settings, the smart-charging switch and the weekly departure schedule —
  there is intentionally no fake start/stop control.
- **Away-mode switch is optimistic** (`assumed_state`): the API has no field to
  read its current on/off state back. (The smart-charging switch, by contrast,
  reads its real state from the vehicle settings.)
- **Grid Rewards** is fetched in a separate, error-tolerant request and only
  exposed for homes that actually have rewards history — the `gridRewardsHistoryPeriod`
  query errors for homes without data, so it must not share the combined poll query.
- Battery, inverter and thermostat entities are implemented from the documented
  schema and **field-name-verified against the live API** (e.g. the `batteryState`
  subscription validates), but their *values* are untested because the account has
  no such device. The thermostat HVAC-mode string mapping is a best-effort guess.

### Intentionally not implemented

- **Generic home `sensors`** (temperature/humidity) — the `Sensor` type exposes no
  name/type, only a bare measurement, so entities would be unidentifiable.
- **Per-device consumption history** (`evChargerConsumption`,
  `electricVehicleConsumption`, battery timeline/aggregated history) — chart data
  better suited to the app; live power + month-to-date totals are covered instead.
- **Account wallet/invoices** — the `Wallet` type exposes no balance field.
- **Bridge (Zigbee gateway), device pairing/onboarding, messages/offers/checklist,
  gizmo visibility, push-notification inbox** — app-management actions, not
  smart-home entities.
- **Grid Rewards live WS state / all-time total** — only the polled current-month
  total is exposed.
