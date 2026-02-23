# OBS WebSocket Integration for Home Assistant

A custom Home Assistant integration that monitors OBS Studio via the WebSocket v5 protocol. Provides real-time stream status and service configuration as sensors using a persistent connection with event-driven updates.

## Requirements

- Home Assistant 2024.1+
- OBS Studio 28+ (ships with WebSocket v5)
- WebSocket server enabled in OBS (Tools > WebSocket Server Settings)

## Installation

1. Copy the `obs_websocket` folder to your Home Assistant `custom_components` directory:

   ```
   custom_components/
   └── obs_websocket/
       ├── __init__.py
       ├── config_flow.py
       ├── const.py
       ├── manifest.json
       ├── sensor.py
       └── strings.json
   ```

2. Restart Home Assistant.

3. Go to **Settings > Devices & Services > Add Integration** and search for **OBS WebSocket**.

4. Enter your OBS machine's hostname/IP, port (default `4455`), and password (if authentication is enabled in OBS).

## OBS Setup

1. Open OBS Studio.
2. Go to **Tools > WebSocket Server Settings**.
3. Check **Enable WebSocket server**.
4. Note the port (default `4455`).
5. If **Enable Authentication** is checked, copy the password for the HA config flow. You can also uncheck it if your network is trusted.

## Sensors

### Stream Status (`sensor.obs_stream_status`)

| State | Description |
|-------|-------------|
| `streaming` | OBS is actively streaming |
| `reconnecting` | Stream is reconnecting |
| `idle` | Not streaming |

**Attributes:**

| Attribute | Description |
|-----------|-------------|
| `output_bytes` | Total bytes sent |
| `output_duration` | Stream duration |
| `output_timecode` | Stream timecode |
| `output_skipped_frames` | Number of skipped frames |
| `output_total_frames` | Total frames transmitted |
| `output_congestion` | Network congestion value |

### Stream Service (`sensor.obs_stream_service`)

State is the service type (e.g. `rtmp_common`).

**Attributes:**

| Attribute | Description |
|-----------|-------------|
| `stream_service_settings` | Dict containing `server`, `key`, and other service-specific fields |

## Configuration

| Field | Default | Description |
|-------|---------|-------------|
| Host | `localhost` | Hostname or IP of the OBS machine |
| Port | `4455` | WebSocket server port |
| Password | *(empty)* | WebSocket password (leave blank if auth is disabled) |

## Architecture

The integration uses a dual-client persistent connection model:

- **ReqClient** handles synchronous API requests (fetching stream status and service settings).
- **EventClient** listens for `on_stream_state_changed` events and triggers immediate sensor updates.
- A **DataUpdateCoordinator** provides a 60-second heartbeat poll as a fallback, with event-driven refreshes for real-time responsiveness.

If the connection drops, the coordinator automatically reconnects on the next update cycle.

## Dependencies

- [`obsws-python==1.8.0`](https://pypi.org/project/obsws-python/) - OBS WebSocket v5 Python library
