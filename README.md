# OBS WebSocket Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

[OBS Studio](https://obsproject.com/) is a free, open-source application for video recording and live streaming. It is widely used by content creators, gamers, and professionals for streaming to platforms such as Twitch, YouTube, and Facebook Live.

This custom Home Assistant integration connects to OBS Studio via the [WebSocket v5 protocol](https://github.com/obsproject/obs-websocket), exposing real-time stream status, recording status, stream health and performance statistics, and service configuration as sensors, a snapshot camera of the program output, and buttons to start and stop streaming and recording. It uses a persistent connection with event-driven updates for near-instant state changes.

## Requirements

- Home Assistant 2024.1+
- OBS Studio 28+ (ships with WebSocket v5)
- WebSocket server enabled in OBS (Tools > WebSocket Server Settings)
- Network connectivity between Home Assistant and the OBS machine

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** > three-dot menu > **Custom repositories**
3. Add this repository URL and select **Integration** as the category
4. Search for and install **OBS WebSocket**
5. Restart Home Assistant

### Manual

1. Copy the `obs_websocket` folder to your Home Assistant `custom_components` directory:

   ```
   custom_components/
   └── obs_websocket/
       ├── __init__.py
       ├── button.py
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

#### Record Status

Reports the current recording state of OBS. This is independent of the stream status, so OBS can be streaming and recording at the same time.

| State | Description |
|-------|-------------|
| `recording` | OBS is actively recording |
| `paused` | Recording is paused |
| `idle` | Not recording |

**Attributes:**

| Attribute | Description |
|-----------|-------------|
| `output_bytes` | Total bytes written |
| `output_duration` | Recording duration in milliseconds |
| `output_timecode` | Recording timecode (HH:MM:SS.mmm) |

#### Stream Service (Diagnostic)

Reports the configured streaming service. State is the service type (e.g. `rtmp_common`).

**Attributes:**

| Attribute | Description |
|-----------|-------------|
| `stream_service_settings` | Dict containing `server`, `key`, and other service-specific fields |

#### Performance and Stream Health

Numeric sensors from OBS's `GetStats` and stream status. OBS's frame counters are cumulative (since OBS or the output started), which hides whether frames are being lost *now*, so the percentage sensors are measured over the window since the previous update (at least 10 seconds; usually the 60-second poll). The cumulative counts are kept as `skipped_frames` / `total_frames` attributes.

| Sensor | Unit | Description |
|--------|------|-------------|
| Active FPS | fps | Frames per second OBS is actually rendering; below your configured FPS means OBS is falling behind. |
| Render skipped frames | % | Frames the renderer missed (GPU overloaded, or the app throttled). |
| Encoding lagged frames | % | Frames skipped because the encoder could not keep up (CPU/encoder overloaded). |
| Stream dropped frames | % | Frames dropped by the stream output (network). Unknown when not streaming. |
| Stream congestion | % | OBS's congestion estimate for the stream output. Unknown when not streaming. |
| Stream bitrate | kbit/s | Upload bitrate over the last window; 0 when not streaming. |
| Available disk space | GB | Free space on the recording drive. |
| CPU usage *(diagnostic, disabled by default)* | % | OBS process CPU usage. |
| Memory usage *(diagnostic, disabled by default)* | MB | OBS process memory. |
| Average frame render time *(diagnostic, disabled by default)* | ms | Average time to render a frame. |

### Camera

#### Program *(disabled by default)*

A still image of the current program scene — what is going to the stream and recording — taken with `GetSourceScreenshot` each time the frontend or an automation asks for one (JPEG, scaled to fit the requested size, 1280 px by default). Rendering a screenshot costs OBS some GPU time, so enable it only where it is useful, e.g. a dashboard picture card or a pre-service check that snapshots the output.

### Buttons

#### Start Stream

Press to start streaming in OBS. Raises an error if OBS is unreachable or the stream cannot be started (e.g. already streaming).

#### Stop Stream

Press to stop streaming in OBS. Raises an error if OBS is unreachable or the stream cannot be stopped (e.g. not currently streaming).

#### Start Recording

Press to start recording in OBS, to the output path set in OBS. Independent of streaming. Raises an error if OBS is unreachable or recording cannot be started (e.g. already recording).

#### Stop Recording

Press to stop recording in OBS. Raises an error if OBS is unreachable or recording cannot be stopped (e.g. not currently recording).

## Configuration

| Field | Default | Description |
|-------|---------|-------------|
| Host | `localhost` | Hostname or IP of the OBS machine |
| Port | `4455` | WebSocket server port |
| Password | *(empty)* | WebSocket password (leave blank if auth is disabled) |

After initial setup, you can reconfigure the connection (host, port, password) via the integration's three-dot menu > **Reconfigure**. If the password changes on the OBS side, use **Re-authenticate**.

## Data Updates

The integration maintains a persistent WebSocket connection to OBS with two update mechanisms:

- **Event-driven (primary):** The `EventClient` listens for `StreamStateChanged` and `RecordStateChanged` events from OBS, triggering an immediate sensor refresh when the stream or recording starts, stops, pauses, or reconnects.
- **Heartbeat poll (fallback):** A `DataUpdateCoordinator` polls OBS every **60 seconds** to sync state in case an event is missed or the connection was briefly interrupted.

The performance and stream-health sensors update on the same poll (and on stream/record events), so their resolution is about a minute. The program camera fetches a new screenshot on demand instead.

Requests are sent one at a time over the connection: `obsws-python` does not match replies to request IDs, so overlapping requests (a poll, a button press, a camera snapshot) could otherwise receive each other's replies.

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

**Alert on dropped frames while live:**

```yaml
automation:
  - alias: "Alert frame drops"
    trigger:
      - platform: numeric_state
        entity_id: sensor.obs_studio_stream_dropped_frames
        above: 2
        for: "00:02:00"
    action:
      - service: notify.mobile_app
        data:
          message: "OBS is dropping {{ states('sensor.obs_studio_stream_dropped_frames') }}% of stream frames"
```

**Warn when OBS can't keep up before going live:**

```yaml
automation:
  - alias: "OBS rendering behind"
    trigger:
      - platform: numeric_state
        entity_id: sensor.obs_studio_render_skipped_frames
        above: 5
        for: "00:05:00"
    action:
      - service: notify.mobile_app
        data:
          message: >
            OBS is skipping {{ states('sensor.obs_studio_render_skipped_frames') }}% of rendered
            frames ({{ states('sensor.obs_studio_active_fps') }} fps)
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

- **Stream monitoring dashboards** - Display stream status, bitrate, dropped frames, and a snapshot of the program output on a Lovelace dashboard.
- **Automated notifications** - Get alerts on your phone when a stream starts, stops, or experiences issues.
- **Smart home integration** - Trigger lights, cameras, or "on air" signs when you go live.
- **Uptime tracking** - Log stream duration and stability over time using the recorder.

## Known Limitations

- **Synchronous library** - The underlying `obsws-python` library uses threads rather than asyncio, so all calls are wrapped with `async_add_executor_job`.
- **Single stream output** - Only the primary stream output is monitored. Virtual cam and replay buffer status are not currently tracked.
- **No auto-discovery** - You must manually enter the OBS host and port; the integration cannot discover OBS instances on the network.
- **No device firmware version** - The OBS version is not currently reported in device info.
- **Minute resolution** - Performance and stream-health sensors are polled about once a minute; short spikes between polls are averaged into the window.

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| "Failed to connect to OBS WebSocket" during setup | Verify OBS is running and the WebSocket server is enabled in Tools > WebSocket Server Settings. Check that the host, port, and password are correct. |
| Sensors show "unavailable" | OBS may have been closed or the network connection was lost. The integration will automatically reconnect within 60 seconds when OBS becomes reachable. |
| State doesn't update immediately | Verify OBS is version 28+. Older versions may not emit WebSocket v5 events. The fallback poll interval is 60 seconds. |
| Integration won't load after HA update | Check the Home Assistant logs for errors. You may need to update the `obsws-python` dependency or the integration code. |
| Password changed in OBS | Home Assistant shows a **Re-authenticate** prompt under **Settings > Devices & Services**; enter the new password there. To change the host or port as well, use **(three-dot menu) > Reconfigure**. |

## Dependencies

- [`obsws-python==1.8.0`](https://pypi.org/project/obsws-python/) - OBS WebSocket v5 Python library
