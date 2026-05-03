# CozyLife & Home Assistant

CozyLife Home Assistant integration for controlling CozyLife smart devices via the CozyLife cloud relay.

> **Note:** This is a community fork of the original integration. The original relied on local TCP (port 5555)
> and LAN UDP discovery, which are blocked in CozyLife firmware 1.0.2 and later. This fork replaces the
> local protocol with the CozyLife cloud relay (`139.162.135.94:8899`), making it compatible with current
> firmware without requiring LAN access to the device.


## Supported Device Types

- RGBCW Light
- CW Light
- Switch & Plug


## Requirements

- Home Assistant 2024.1 or later
- Your device's **DID** (Device ID) and **device key** — obtained from a network capture of the CozyLife
  app (see [Obtaining device credentials](#obtaining-device-credentials) below)
- A CozyLife account **auth token** — also obtained from a network capture


## Install

1. Copy the `custom_components/hass_cozylife_local_pull` folder into your HA `custom_components` directory.
2. Add the following to your `configuration.yaml`:

```yaml
hass_cozylife_local_pull:
  lang: en
  token: YOUR_AUTH_TOKEN
  device_keys:
    YOUR_DEVICE_DID: YOUR_DEVICE_KEY
  ip:
    - "192.168.x.x"   # IP of the device (used for UDP info attempt; relay is used as fallback)
```

3. Restart Home Assistant.


## Obtaining device credentials

The `token`, device DID, and device key are not exposed in the CozyLife app UI. You need to capture
network traffic from the CozyLife app while it connects to a device:

1. Use a traffic capture tool (e.g. PCAPdroid on Android, or a MITM proxy) on the phone running the
   CozyLife app.
2. Filter traffic to/from `139.162.135.94` port `8899`.
3. Look for lines containing `cmd=auth&token=` — the token value is your auth token.
4. Look for lines containing `cmd=subscribe` — the `device_id` field is your DID and `device_key` is
   your device key.


## How it works (post-firmware-1.0.2)

CozyLife firmware 1.0.2 and later block inbound TCP connections on port 5555. LAN UDP discovery
(port 6095) is also unreachable from HA when running in a Docker container on a different subnet.

This fork communicates exclusively through the CozyLife cloud relay:

- **Device info** — on startup, a temporary relay connection is opened to retrieve device metadata
  (PID, model name, data-point IDs). If LAN UDP succeeds it is used instead.
- **Persistent control connection** — a background thread maintains a persistent TCP connection to the
  relay, re-connecting on failure.
- **State polling** — `query` commands are sent via the relay every 30 seconds.
- **Control** — `set` commands (on/off, brightness, colour temperature, colour) are published to the
  relay and the device responds within ~100 ms.

The relay uses a line-oriented text protocol:
```
cmd=auth&token=TOKEN\r\n
cmd=subscribe&topic=device_DID&from=control&device_id=DID&device_key=KEY\r\n
cmd=publish&device_id=DID&topic=control_DID&device_key=KEY&message={json}\r\n
```


## Changes from the original integration

| Area | Original | This fork |
|---|---|---|
| Device communication | Local TCP port 5555 | Cloud relay `139.162.135.94:8899` |
| Device discovery | LAN UDP broadcast port 6095 | Relay CMD_INFO fallback (UDP attempted first) |
| Firmware compatibility | 1.0.0 – 1.0.1 | 1.0.2+ |
| Required config | `ip` only | `ip`, `token`, `device_keys` |
| HA async safety | Blocking calls on event loop | All blocking I/O in executor threads |
| Deprecated HA APIs | Used old `COLOR_MODE_*`, `SUPPORT_*` constants | Updated to `ColorMode` enum, `LightEntityFeature` |
| Color temperature | `min_mireds`/`max_mireds` | `min_color_temp_kelvin`/`max_color_temp_kelvin` |
| Platform setup | Sync `setup_platform` | Async `async_setup_platform` |


## Bug fixes applied to the original code

1. **Sync `setup_platform` → `async_setup_platform`** in `light.py` and `switch.py` — the original
   used synchronous setup functions in an async HA environment.
2. **Shared mutable class-level state** — device state dicts were defined at class level (shared across
   all instances); moved to `__init__`.
3. **Deprecated `ColorMode` constants** — replaced `COLOR_MODE_*` strings with the `ColorMode` enum.
4. **Deprecated `SUPPORT_*` feature flags** — replaced with `LightEntityFeature` flags.
5. **Deprecated color temperature attributes** — replaced `min_mireds`/`max_mireds` with
   `min_color_temp_kelvin`/`max_color_temp_kelvin`.
6. **Blocking I/O on the HA event loop** — all socket I/O and `time.sleep` calls moved to executor
   threads via `hass.async_add_executor_job`.
7. **TCP port 5555 blocked in firmware 1.0.2** — replaced local TCP with cloud relay protocol.


## Troubleshoot

- Confirm your `token` and `device_keys` values are correct (re-capture if needed).
- Check HA logs at `Settings → System → Logs` or enable debug logging:
  ```yaml
  logger:
    logs:
      custom_components.hass_cozylife_local_pull: debug
  ```
- If `Device info` line does not appear in logs, the relay auth token or device key is wrong.
- If entities are created but state is always unavailable, check that the relay connection stays up
  (look for repeated `Relay connected` log lines which indicate reconnect loops).


## Feedback

- Please submit an issue on GitHub.


## TODO

- Support config flow (UI-based setup instead of `configuration.yaml`)
- Support sensor device types
- Support multiple devices with independent keys
