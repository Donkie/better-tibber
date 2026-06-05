# Tibber app — Home Assistant integration

A Home Assistant custom component that connects to the **Tibber mobile app** GraphQL
API (`app.tibber.com`) and exposes it as native entities: EV and charger control, a
live real-time meter, electricity prices, Grid Rewards, weather, and — where present
— home battery, solar inverter and thermostats.

> ⚠️ **Unofficial.** Not endorsed by Tibber; the API may change without notice. Use
> your own account and respect the rate limit.

## Features

- **Vehicles** — battery %, range, charging status, session energy/cost, manual
  state-of-charge, smart-charging toggle and a **weekly departure schedule** (a
  `time` entity per weekday).
- **Chargers** — status, preferred-vehicle selector, cable lock, load balancing,
  fuse/current settings.
- **Live meter (Pulse)** — power, production, per-phase current/voltage and running
  consumption/cost, streamed over WebSocket.
- **Home** — current electricity price (+ today/tomorrow), month-to-date
  consumption & cost, Grid Rewards, an hourly `weather` entity, away mode and peak
  control.
- **Battery / solar / thermostat** — state of charge and power flows, production,
  and a full `climate` entity where such devices exist.

See the [component README](custom_components/tibber_app/README.md) for the full
entity list and notes.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add this repository, category **Integration**.
2. Install **Tibber (unofficial app API)**, then restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → “Tibber (unofficial app API)”**
   and sign in with your Tibber app email + password.

### Manual

Copy `custom_components/tibber_app/` into your Home Assistant
`config/custom_components/` directory and restart.

## Development

- [QUICKSTART.md](QUICKSTART.md) — run the integration in a local Home Assistant.
- CI runs `hassfest`, the HACS action and `ruff` (see `.github/workflows/`).
