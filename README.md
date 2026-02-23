# OBS WebSocket Integration for Home Assistant

[OBS Studio](https://obsproject.com/) is a free, open-source application for video recording and live streaming. It is widely used by content creators, gamers, and professionals for streaming to platforms such as Twitch, YouTube, and Facebook Live.

This custom Home Assistant integration connects to OBS Studio via the [WebSocket v5 protocol](https://github.com/obsproject/obs-websocket), exposing real-time stream status and service configuration as sensors. It uses a persistent connection with event-driven updates for near-instant state changes.

## Requirements

- Home Assistant 2024.1+
- OBS Studio 28+ (ships with WebSocket v5)
- WebSocket server enabled in OBS (Tools > WebSocket Server Settings)
- Network connectivity between Home Assistant and the OBS machine

## Installation

1. Copy the `obs_websocket` folder to your Home Assistant `custom_components` directory:

   ```
   custom_components/
   └── obs_websocket/
       ├── __init__.py
       ├── config_flow.py
       ├── const.py
       ├── icons.json
       ├── manifest.json
       ├── sensor.py
       └── strings.json
   ```

2. Restart Home Assistant.

3. Go to **Settings > Devices & Services > Add Integration** and search for **OBS WebSocket**.

4. Enter your OBS machine's hostname/IP, port (default `4455`), and password (if authentication is enabled in OBS).

## Removal

1. Go to **Settings > Devices & Services**.
2. Find the **OBS WebSocket** integration entry.
3. Click the three-dot menu and select **Delete**.
4. Optionally remove the `obs_websocket` folder from `custom_components` and restart Home Assistant.

## OBS Setup

1. Open OBS Studio.
2. Go to **Tools > WebSocket Server Settings**.
3. Check **Enable WebSocket server**.
4. Note the port (default `4455`).
5. If **Enable Authentication** is checked, copy the password for the HA config flow. You can also uncheck it if your network is trusted.

## Supported Devices

This integration supports any instance of **OBS Studio 28 or newer** running on Windows, macOS, or Linux. Older versions of OBS that do not include the built-in WebSocket v5 server are not supported.

## Supported Functions

### Sensors

#### Stream Status

Reports the current streaming state of OBS.

| State | Description |
|-------|-------------|
| `streaming` | OBS is actively streaming |
| `reconnecting` | Stream is reconnecting |
| `idle` | Not streaming |

**Attributes:**

| Attribute | Description |
|-----------|-------------|
| `output_bytes` | Total bytes sent |
| `output_duration` | Stream duration in milliseconds |
| `output_timecode` | Stream timecode (HH:MM:SS.mmm) |
| `output_skipped_frames` | Number of skipped frames |
| `output_total_frames` | Total frames transmitted |
| `output_congestion` | Network congestion value (0.0 - 1.0) |

#### Stream Service (Diagnostic)

Reports the configured streaming service. State is the service type (e.g. `rtmp_common`).

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

After initial setup, you can reconfigure the connection (host, port, password) via the integration's three-dot menu > **Reconfigure**. If the password changes on the OBS side, use **Re-authenticate**.

## Data Updates

The integration maintains a persistent WebSocket connection to OBS with two update mechanisms:

- **Event-driven (primary):** The `EventClient` listens for `StreamStateChanged` events from OBS, triggering an immediate sensor refresh when the stream starts, stops, or reconnects.
- **Heartbeat poll (fallback):** A `DataUpdateCoordinator` polls OBS every **60 seconds** to sync state in case an event is missed or the connection was briefly interrupted.

If the connection to OBS drops, sensors are marked **unavailable** and the coordinator attempts to reconnect on the next poll cycle.

## Automation Examples

**Notify when streaming starts:**

```yaml
automation:
  - alias: "Notify stream started"
    trigger:
      - platform: state
        entity_id: sensor.obs_stream_status
        to: "streaming"
    action:
      - service: notify.mobile_app
        data:
          message: "OBS is now streaming!"
```

**Alert on high frame skipping:**

```yaml
automation:
  - alias: "Alert frame drops"
    trigger:
      - platform: template
        value_template: >
          {{ state_attr('sensor.obs_stream_status', 'output_skipped_frames') | int > 100 }}
    action:
      - service: notify.mobile_app
        data:
          message: "OBS has skipped {{ state_attr('sensor.obs_stream_status', 'output_skipped_frames') }} frames"
```

**Turn off lights when stream goes live:**

```yaml
automation:
  - alias: "Stream mode lighting"
    trigger:
      - platform: state
        entity_id: sensor.obs_stream_status
        to: "streaming"
    action:
      - service: light.turn_off
        target:
          area_id: office
```

## Use Cases

- **Stream monitoring dashboards** - Display stream status, uptime, and frame statistics on a Lovelace dashboard.
- **Automated notifications** - Get alerts on your phone when a stream starts, stops, or experiences issues.
- **Smart home integration** - Trigger lights, cameras, or "on air" signs when you go live.
- **Uptime tracking** - Log stream duration and stability over time using the recorder.

## Known Limitations

- **Read-only** - This integration monitors OBS but does not control it (no start/stop stream actions).
- **Synchronous library** - The underlying `obsws-python` library uses threads rather than asyncio, so all calls are wrapped with `async_add_executor_job`.
- **Single stream output** - Only the primary stream output is monitored. Recording status and virtual cam status are not currently tracked.
- **No auto-discovery** - You must manually enter the OBS host and port; the integration cannot discover OBS instances on the network.
- **No device firmware version** - The OBS version is not currently reported in device info.

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| "Failed to connect to OBS WebSocket" during setup | Verify OBS is running and the WebSocket server is enabled in Tools > WebSocket Server Settings. Check that the host, port, and password are correct. |
| Sensors show "unavailable" | OBS may have been closed or the network connection was lost. The integration will automatically reconnect within 60 seconds when OBS becomes reachable. |
| State doesn't update immediately | Verify OBS is version 28+. Older versions may not emit WebSocket v5 events. The fallback poll interval is 60 seconds. |
| Integration won't load after HA update | Check the Home Assistant logs for errors. You may need to update the `obsws-python` dependency or the integration code. |
| Password changed in OBS | Use **Settings > Devices & Services > OBS WebSocket > (three-dot menu) > Re-authenticate** to update the password. |

## Dependencies

- [`obsws-python==1.8.0`](https://pypi.org/project/obsws-python/) - OBS WebSocket v5 Python library
