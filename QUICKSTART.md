# Quickstart — run the integration in a local Home Assistant

Run all commands from the repo root.

## 1. Start HA with the integration mounted (Docker — recommended)

```bash
mkdir -p ~/ha-test/config
docker run -d --name ha-tibber -p 8123:8123 \
  -v ~/ha-test/config:/config \
  -v "$PWD/custom_components/tibber_app:/config/custom_components/tibber_app" \
  ghcr.io/home-assistant/home-assistant:stable
docker logs -f ha-tibber          # watch startup; Ctrl-C to stop tailing
```

Open <http://localhost:8123>, create the onboarding account, then:
**Settings → Devices & Services → Add Integration → “Better Tibber”**
and enter your Tibber email + password.

## 2. After changing the code

```bash
docker restart ha-tibber && docker logs -f ha-tibber
```

(The integration is mounted live, so no re-copy — a restart reloads it.)

## 3. Inspect / debug

```bash
docker logs ha-tibber 2>&1 | grep -i tibber_app   # integration logs
```

Enable debug logging by adding this to `~/ha-test/config/configuration.yaml`, then restart:

```yaml
logger:
  default: warning
  logs:
    custom_components.tibber_app: debug
```

## 4. Tear down

```bash
docker rm -f ha-tibber
```

---

### Alternative: Python venv (no Docker)

```bash
python3 -m venv ~/ha-venv && source ~/ha-venv/bin/activate
pip install homeassistant
mkdir -p ~/ha-test/custom_components
ln -sfn "$PWD/custom_components/tibber_app" ~/ha-test/custom_components/tibber_app
hass -c ~/ha-test                 # first run downloads deps; then open :8123
```

Restart `hass` (Ctrl-C and re-run) to pick up code changes.
