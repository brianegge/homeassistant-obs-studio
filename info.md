# OBS WebSocket Integration

Connect Home Assistant to OBS Studio via WebSocket v5 to monitor and control streaming, recording, the virtual camera and scenes.

## Features

- **Stream and record status sensors** - streaming, reconnecting or idle; recording, paused or idle
- **Stream health and performance sensors** - FPS, skipped and dropped frames, congestion, bitrate, disk space
- **Stream service sensor** - configured streaming service and settings
- **Program camera** - a snapshot of what OBS is sending out (disabled by default)
- **Buttons** - start and stop streaming and recording
- **Virtual camera switch** - start and stop the OBS virtual camera
- **Scene select** - see and switch the program scene
- **Event-driven updates** - near-instant state changes via WebSocket
- **Heartbeat polling** - fallback sync every 60 seconds

## Requirements

- OBS Studio 28+ (with WebSocket v5)
- WebSocket server enabled in OBS
