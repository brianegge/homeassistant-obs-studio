# AGENTS.md - OBS WebSocket Integration

## Project Overview

Custom Home Assistant integration (`obs_websocket`) that monitors OBS Studio via WebSocket v5. It exposes two sensor entities for stream status and service configuration, grouped under a device.

## Directory Structure

```
obs_websocket/
├── __init__.py       # Core: OBSConnection, OBSCoordinator, OBSRuntimeData, OBSConfigEntry
├── config_flow.py    # Config flow: user setup, reauth, reconfigure
├── const.py          # Constants: DOMAIN, defaults, HEARTBEAT_INTERVAL, PLATFORMS
├── icons.json        # Icon translations (per-state icons for sensors)
├── manifest.json     # Integration metadata and dependencies
├── sensor.py         # Sensor entities: OBSStreamStatusSensor, OBSStreamServiceSensor
├── strings.json      # UI localization: config flow, entity names/states, exceptions
├── README.md         # User-facing documentation
└── AGENTS.md         # This file
```

## Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `OBSRuntimeData` | `__init__.py` | Typed dataclass stored in `ConfigEntry.runtime_data` |
| `OBSConfigEntry` | `__init__.py` | Type alias: `ConfigEntry[OBSRuntimeData]` |
| `OBSConnection` | `__init__.py` | Manages persistent ReqClient + EventClient WebSocket connections |
| `OBSCoordinator` | `__init__.py` | DataUpdateCoordinator with 60s heartbeat, event-driven refresh, availability logging |
| `OBSWebSocketConfigFlow` | `config_flow.py` | Config flow with user setup, reauth, and reconfigure steps |
| `OBSSensorBase` | `sensor.py` | Base class with `has_entity_name`, `DeviceInfo` |
| `OBSStreamStatusSensor` | `sensor.py` | Stream state sensor (streaming/reconnecting/idle) |
| `OBSStreamServiceSensor` | `sensor.py` | Stream service type and settings sensor (diagnostic) |

## Important Constants (`const.py`)

- `DOMAIN = "obs_websocket"`
- `DEFAULT_HOST = "localhost"`
- `DEFAULT_PORT = 4455`
- `HEARTBEAT_INTERVAL = 60` (seconds)
- `PLATFORMS = ["sensor"]`

## Connection Architecture

The integration uses two persistent `obsws_python` connections:

1. **ReqClient** - Sends requests to OBS (get_stream_status, get_stream_service_settings).
2. **EventClient** - Subclassed to override `on_stream_state_changed`, which triggers an async coordinator refresh via `asyncio.run_coroutine_threadsafe`.

Both clients run in the executor (blocking I/O) and are wrapped with `hass.async_add_executor_job`.

When the connection drops, the coordinator logs a warning, marks entities unavailable (via `UpdateFailed`), and reconnects on the next poll cycle.

## Conventions

- Follow Home Assistant custom component conventions and patterns.
- All blocking I/O must be wrapped with `hass.async_add_executor_job`.
- Use `ConfigEntry.runtime_data` (typed `OBSRuntimeData`) instead of `hass.data[DOMAIN]`.
- Use `has_entity_name = True` with `translation_key` for entity names.
- Sensor states should be simple strings (`streaming`, `idle`, `reconnecting`).
- Extra data goes in entity attributes, not state.
- Config flow unique ID is `{host}:{port}` to prevent duplicate entries.
- The `obsws_python` library is imported lazily inside functions that run in the executor.
- Icons are defined in `icons.json`, not hardcoded as `_attr_icon`.
- All user-facing strings go in `strings.json` with translation keys.

## Adding New Functionality

### Adding a new sensor
1. Subclass `OBSSensorBase` in `sensor.py`.
2. Set `_attr_translation_key` and `_attr_unique_id`.
3. Add it to the `async_setup_entry` entity list in `sensor.py`.
4. Add name/state translations to `strings.json` and icons to `icons.json`.
5. If it needs new data, update `OBSConnection.async_fetch_data()` in `__init__.py`.

### Adding a new platform (e.g. switch, button)
1. Create a new platform file (e.g. `switch.py`).
2. Add the platform name to `PLATFORMS` in `const.py`.
3. Implement `async_setup_entry` in the new platform file.
4. Access the coordinator via `entry.runtime_data.coordinator`.

### Adding services
1. Create `services.yaml` with service definitions.
2. Register services in `async_setup_entry` in `__init__.py` using `hass.services.async_register`.
3. Use `OBSConnection._req_client` to call OBS WebSocket methods.

### Adding new event listeners
1. Add new `on_*` methods to the `_Events` subclass inside `OBSConnection.async_connect()`.
2. Trigger coordinator refresh or handle state updates in the callback.

## Dependencies

- `obsws-python==1.8.0` - pinned in `manifest.json`
- Home Assistant core (ConfigEntry, DataUpdateCoordinator, SensorEntity)

## Testing

No test suite currently exists. When adding tests:
- Use `pytest-homeassistant-custom-component` for HA integration testing.
- Mock `obsws_python.ReqClient` and `obsws_python.EventClient`.
- Test config flow validation (user, reauth, reconfigure), coordinator updates, and sensor state mapping.
