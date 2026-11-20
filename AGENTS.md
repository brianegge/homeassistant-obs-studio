# AGENTS.md - OBS WebSocket Integration

## Project Overview

Custom Home Assistant integration (`obs_websocket`) that monitors OBS Studio via WebSocket v5. It exposes sensors for stream status, recording status, stream health and service configuration, a program snapshot camera, start/stop buttons, a virtual camera switch and a program scene select, all grouped under one device.

## Directory Structure

```
homeassistant-obs-studio/        # Git repo root
├── custom_components/
│   └── obs_websocket/
│       ├── brand/               # Integration icons shown in Home Assistant and HACS
│       ├── __init__.py          # Core: OBSConnection, OBSCoordinator, OBSRateTracker, OBSRuntimeData, parsing helpers
│       ├── button.py            # Buttons: start/stop stream, start/stop recording
│       ├── camera.py            # Program snapshot camera (GetSourceScreenshot of the program scene)
│       ├── config_flow.py       # Config flow: user setup, reauth, reconfigure
│       ├── const.py             # Constants: DOMAIN, defaults, HEARTBEAT_INTERVAL, PLATFORMS, REFRESH_EVENTS
│       ├── diagnostics.py       # Diagnostics support
│       ├── errors.py            # OBSAuthError, is_auth_error (rejected password), is_request_error (OBS error status)
│       ├── icons.json           # Icon translations for every entity (per-state where useful)
│       ├── manifest.json        # Integration metadata and dependencies
│       ├── py.typed             # Marks the package as typed
│       ├── quality_scale.yaml   # Home Assistant integration quality scale self-assessment
│       ├── select.py            # Program scene select (GetSceneList / SetCurrentProgramScene)
│       ├── sensor.py            # Sensor entities: status sensors + description-driven OBSStatSensor
│       ├── strings.json         # UI localization: config flow, entity names/states, exceptions
│       ├── switch.py            # Virtual camera switch (GetVirtualCamStatus / Start/StopVirtualCam)
│       └── translations/
│           └── en.json          # Copy of strings.json; HA only loads translations/ for custom integrations
├── tests/                       # Test suite
│   ├── conftest.py
│   ├── test_button.py
│   ├── test_config_flow.py
│   ├── test_diagnostics.py
│   ├── test_init.py
│   ├── test_select.py
│   ├── test_sensor.py
│   ├── test_stats.py
│   └── test_switch.py
├── .github/                     # GitHub config: dependabot, labeler, workflows (tests, lint, hassfest, HACS validate, release)
├── hacs.json                    # HACS repository metadata
├── info.md                      # Short HACS description
├── README.md                    # User-facing documentation
├── AGENTS.md                    # This file
├── pyproject.toml               # Ruff and mypy settings
├── requirements.test.txt        # Test dependencies (no obsws-python, see Testing)
└── pytest.ini                   # Pytest configuration
```

## Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `OBSRuntimeData` | `__init__.py` | Typed dataclass stored in `ConfigEntry.runtime_data` |
| `OBSConfigEntry` | `__init__.py` | Type alias: `ConfigEntry[OBSRuntimeData]` |
| `OBSConnection` | `__init__.py` | Manages persistent ReqClient + EventClient WebSocket connections |
| `OBSCoordinator` | `__init__.py` | DataUpdateCoordinator with 60s heartbeat, event-driven refresh, availability logging |
| `OBSAuthError` | `errors.py` | Raised when OBS rejects the password; becomes `ConfigEntryAuthFailed` (starts reauth) |
| `OBSWebSocketConfigFlow` | `config_flow.py` | Config flow with user setup, reauth, and reconfigure steps |
| `OBSSensorBase` | `sensor.py` | Base class with `has_entity_name`, `DeviceInfo` |
| `OBSStreamStatusSensor` | `sensor.py` | Stream state sensor (streaming/reconnecting/idle) |
| `OBSRecordStatusSensor` | `sensor.py` | Recording state sensor (recording/paused/idle) |
| `OBSStreamServiceSensor` | `sensor.py` | Stream service type and settings sensor (diagnostic) |
| `OBSRateTracker` | `__init__.py` | Turns OBS's cumulative counters into per-window bitrate and skipped-frame percentages (`data["rates"]`) |
| `OBSStatSensor` | `sensor.py` | One numeric sensor per `OBSStatSensorEntityDescription` in `STAT_SENSORS` (GetStats, congestion, rates) |
| `OBSProgramCamera` | `camera.py` | Program snapshot camera, disabled by default |
| `OBSButton` | `button.py` | One button per `OBSButtonEntityDescription` in `BUTTONS`: start/stop stream, start/stop recording |
| `OBSVirtualCameraSwitch` | `switch.py` | Virtual camera on/off; unavailable when OBS has no virtual camera (`data["virtual_cam"] is None`) |
| `OBSSceneSelect` | `select.py` | Program scene select; options and current from `data["scenes"]` |

## Important Constants (`const.py`)

- `DOMAIN = "obs_websocket"`
- `DEFAULT_HOST = "localhost"`
- `DEFAULT_PORT = 4455`
- `HEARTBEAT_INTERVAL = 60` (seconds)
- `EVENT_REFRESH_COOLDOWN = 0.5` (seconds)
- `MIN_RATE_INTERVAL = 10` (seconds; shortest window for rates)
- `DEFAULT_SNAPSHOT_SIZE = 1280`, `SNAPSHOT_QUALITY = 80` (program camera)
- `PLATFORMS = ["button", "camera", "select", "sensor", "switch"]`
- `REFRESH_EVENTS` - snake_case OBS event names that trigger a coordinator refresh (stream, record, virtual cam, program scene, scene list/rename/create/remove, scene collection)

## Connection Architecture

The integration uses two persistent `obsws_python` connections:

1. **ReqClient** - Sends requests to OBS (get_stream_status, get_record_status, get_stream_service_settings, get_stats, get_scene_list, get_virtual_cam_status; get_source_screenshot for the camera; start/stop and set_current_program_scene for commands). obsws-python reads the next reply off the socket without matching request IDs, so every call goes through `OBSConnection._async_request`, which holds `_request_lock` for the duration — never call `_req_client` directly.
2. **EventClient** - For each name in `REFRESH_EVENTS`, `OBSConnection._make_event_handler()` builds a function named `on_<event>` and registers it with `callback.register()` (obsws-python only dispatches events to registered functions, matched by `__name__`). The callback calls `coordinator.async_request_refresh()` via `asyncio.run_coroutine_threadsafe`. The coordinator's debouncer (`immediate=True`, `EVENT_REFRESH_COOLDOWN`) refreshes on the first event and coalesces a burst (STARTING then STARTED) into one trailing refresh.

Both clients run in the executor (blocking I/O) and are wrapped with `hass.async_add_executor_job`.

Coordinator data shape: the raw obsws-python responses under `stream_status`, `record_status`, `service_settings` and `stats`, plus normalised values:
- `scenes`: `{"current": str | None, "names": [str, ...]}` from `parse_scene_list()`. OBS returns scenes bottom first (sceneIndex 0 is the last scene in the dock), so names are sorted by sceneIndex descending to match the Scenes dock.
- `virtual_cam`: `True`/`False`, or `None` when OBS has no virtual camera. OBS answers GetVirtualCamStatus with a request error in that case; `_fetch_virtual_cam()` catches only that (`is_request_error`), sets `_virtual_cam_supported = False` so it is not asked again (obsws-python logs every failed request), and `async_connect()` resets the flag.
- `rates`: from `OBSRateTracker`.

When the connection drops, the coordinator logs a warning, marks entities unavailable (via `UpdateFailed`), and reconnects on the next poll cycle.

If OBS rejects the password (at setup or on reconnect), `OBSConnection` raises `OBSAuthError`, which setup and the coordinator turn into `ConfigEntryAuthFailed` so Home Assistant starts the reauth flow. obsws-python reports this as a generic `OBSSDKError`, so `is_auth_error()` matches on its message; auth failures are not retried.

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
- All user-facing strings go in `strings.json` with translation keys, and must be copied to `translations/en.json` (Home Assistant only reads `translations/` for custom integrations; a test enforces the two match).

## Adding New Functionality

### Adding a new sensor
1. Subclass `OBSSensorBase` in `sensor.py`.
2. Set `_attr_translation_key` and `_attr_unique_id`.
3. Add it to the `async_setup_entry` entity list in `sensor.py`.
4. Add name/state translations to `strings.json` (and `translations/en.json`) and icons to `icons.json`.
5. If it needs new data, update `OBSConnection.async_fetch_data()` in `__init__.py`.

### Adding a new platform (e.g. switch, button)
1. Create a new platform file (e.g. `switch.py`).
2. Add the platform name to `PLATFORMS` in `const.py`.
3. Implement `async_setup_entry` in the new platform file.
4. Access the coordinator via `entry.runtime_data.coordinator`.

### Adding services
1. Create `services.yaml` with service definitions.
2. Register services in `async_setup_entry` in `__init__.py` using `hass.services.async_register`.
3. Call OBS WebSocket methods through `OBSConnection._async_request` (it serializes requests and reconnects a stale socket).

### Adding new event listeners
1. If the event should just refresh the coordinator, add its snake_case name (as obsws-python converts it, e.g. `VirtualcamStateChanged` -> `virtualcam_state_changed`) to `REFRESH_EVENTS` in `const.py`.
2. For anything else, register a function named `on_<event>` with `events.callback.register(...)` in `OBSConnection.async_connect()`; it runs on the EventClient thread, so hop to the event loop before touching Home Assistant state.

## Dependencies

- `obsws-python==1.8.0` - pinned in `manifest.json`
- Home Assistant core (ConfigEntry, DataUpdateCoordinator, SensorEntity)

## Testing

Tests are in `tests/` at the repo root. Run with `pytest` from the repo root.
- Uses `pytest-homeassistant-custom-component` for HA integration testing.
- Mocks `obsws_python.ReqClient` and `obsws_python.EventClient`.
- Covers config flow (user, reauth, reconfigure), coordinator updates, sensor state mapping, buttons, the virtual camera switch, the scene select, and diagnostics.
- `obsws-python` must NOT be installed in the test environment: some tests rely on the import failing outside a patched `sys.modules` block (CI only installs `requirements.test.txt`).
