# 2026-09 introduction video (3 minutes) — production scripts

These are the scripts used on 2026-09-24 to produce the 2:58, 1080p60 introduction video submitted to InnoServe (AI tool category). They are kept here as a reference for producing further videos with the same look and voice. Rendered outputs (frames, mp3, mp4) are not committed.

## Pipeline

| Step | Script | What it does |
|---|---|---|
| 1 | `tts_full.py [rate]` | Narration with Microsoft Edge TTS (`edge-tts`), voice `zh-TW-HsiaoChenNeural`, default rate `+4%`. Writes one mp3 per segment plus word timings. `SEGMENTS` holds the narration text shown in subtitles; `SWAP` replaces polyphones with same-length homophones in the spoken text only (重來 → 蟲來, so 重 is read chóng). |
| 2 | `durations.py` | Reads segment durations to drive the animation timeline. |
| 3 | `record_demo.py`, `record_demo2.py` | Record the real UI (`python main.py serve`, http://127.0.0.1:8000) with a Chrome DevTools Protocol screencast through Playwright. |
| 4 | `video.html` | The whole video as one HTML/CSS/SVG page with a time-driven animation; `#capture` mode exposes `TOTAL`, `START`, and `SUBS` for the renderer. |
| 5 | `render_full.py W K` | Renders `video.html` frame by frame at 60 fps with Playwright (W workers, worker index K; resumable) and writes `timeline.json`. |
| 6 | `mix.py` | Places each narration segment at its start time with ffmpeg, writes `narration.m4a` and the `.srt` subtitles. |

Final assembly (frames + narration + burned-in subtitles) is done with ffmpeg.

## Requirements

Python packages `edge-tts` and `playwright` (then `python -m playwright install chromium`), and `ffmpeg` on PATH. These are not in the project's `requirements.txt` because the application itself does not need them.

## Rules the original video followed

- Debate content shown on screen is a replay of recorded output and is labelled as such on screen; it is never presented as live generation.
- Time savings are stated only as measured system run times, never as estimated hours saved for lawyers.
- Narration says "large language model"; the architecture diagram names Claude (Anthropic).
- No school name, school logo, or advisor name may appear (competition anonymity rule).
