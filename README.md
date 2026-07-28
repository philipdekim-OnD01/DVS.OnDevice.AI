# NRV DVS Raspberry Pi Backup

Raspberry Pi DVS/person-detection prototype backup.

## Contents

- `raspberry-pi/bin`: capture, YOLO, synthesis, dashboard, watchdog helper scripts.
- `raspberry-pi/.config/systemd/user`: user systemd service/timer files.
- `raspberry-pi/.local/state/camera-snapshots`: runtime state, queues, logs, model files, status samples.
- `raspberry-pi/camera_snapshots`: rolling camera snapshots.
- `raspberry-pi/person_snapshots`: person-detected snapshots.
- `raspberry-pi/synthetic_frames`: synthetic DVS grid frames/videos and virtual DVS chunks.
- `raspberry-pi/dvs-rpi-backup-inventory.tsv`: file manifest from the Pi.
- `docs`: architecture, meeting notes, and planning documents.

## Dashboard URLs

- `http://192.168.0.100:8080/`
- `http://192.168.0.100:8080/person`
- `http://192.168.0.100:8080/raspberry-pi5-architecture`
- `http://192.168.0.100:8080/event-synthesis`
- `http://192.168.0.100:8080/fall-plan`
- `http://192.168.0.100:8081/`

See `docs/web_routes.md` for the mapping between dashboard links, routes, and source files.

This is a snapshot backup. For long-term generated image/video history, use Git LFS or object storage.
