# Web Dashboard Routes

This file maps the visible dashboard links to the code and generated assets in this repository.

## Raspberry Pi Web URLs

- Main dashboard: `http://192.168.0.100:8080/`
- Person snapshots: `http://192.168.0.100:8080/person`
- Event synthesis page: `http://192.168.0.100:8080/event-synthesis`
- Fall detection plan: `http://192.168.0.100:8080/fall-plan`
- Synthetic DVS grid dashboard: `http://192.168.0.100:8081/`
- Synthetic DVS player: `http://192.168.0.100:8081/play/<event_id>`

## Code Locations

- 8080 dashboard server: `raspberry-pi/bin/camera_gallery_server.py`
- 8081 synthetic grid server: `raspberry-pi/bin/synthetic_grid_server.py`
- Fall plan HTML asset: `raspberry-pi/fall_detection_plan.html`

## Important Route Implementations

`raspberry-pi/bin/camera_gallery_server.py` contains:

- `/`
- `/person`
- `/event-synthesis`
- `/event-synthesis-video/<name>`
- `/fall-plan`
- `/status.json`
- `/image/<name>`
- `/person-image/<name>`

`raspberry-pi/bin/synthetic_grid_server.py` contains:

- `/`
- `/play/<event_id>`
- `/video/<event_id>`
- `/image/<event_id>/<name>`

## Notes

`/event-synthesis` is not a standalone HTML file. It is rendered dynamically by `render_event_synthesis_page()` inside `camera_gallery_server.py`.

`/fall-plan` serves the generated HTML file `/home/philip/fall_detection_plan.html`, which is backed up as `raspberry-pi/fall_detection_plan.html`.
