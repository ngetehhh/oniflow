# Backend Setup

Oniflow now detects interpolation backends from `config.json`.

## Required config shape

Each backend must provide two profiles:

- `<backend>_anime`
- `<backend>_live_action`

Example:

```json
{
  "gmfss_anime": {
    "cwd": "work\\GMFSS_Fortuna",
    "output_extension": "mp4",
    "command": [
      "{project_root}\\work\\gmfss-venv\\Scripts\\python.exe",
      "inference_video.py",
      "--video",
      "{input}",
      "--output",
      "{output}",
      "--model",
      "train_log_live_union",
      "--fps",
      "{target_fps}",
      "--multi",
      "{multiplier}",
      "--scale",
      "{scale}"
    ]
  },
  "gmfss_live_action": {
    "cwd": "work\\GMFSS_Fortuna",
    "output_extension": "mp4",
    "command": [
      "{project_root}\\work\\gmfss-venv\\Scripts\\python.exe",
      "inference_video.py",
      "--video",
      "{input}",
      "--output",
      "{output}",
      "--model",
      "train_log_live_union",
      "--fps",
      "{target_fps}",
      "--multi",
      "{multiplier}",
      "--scale",
      "{scale}"
    ]
  }
}
```

## Supported placeholders

- `{project_root}`
- `{input}`
- `{output}`
- `{target_fps}`
- `{multiplier}`
- `{scale}`
- `{temp_dir}`

## UI behavior

If a backend has both profiles, it appears automatically in the Oniflow model selector.

## Current status

- `GMFSS` is active
- second backend infrastructure is ready
- no second backend weights or runtime are bundled yet
