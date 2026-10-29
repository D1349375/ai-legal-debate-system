# 2026-10 business-governance category video (3 minutes) — production scripts

Scripts used on 2026-10-04 to produce the 2:55, 1080p60 video for the InnoServe business-governance AI category. The narration is `narration.md` v3; `HANDOFF.md` holds the rules and facts the video must follow. Same look and voice as the previous video (`../2026-09-ai-tool-intro/`): HTML/CSS/SVG animation rendered frame by frame, Microsoft Edge TTS narration, real UI recording. Rendered outputs (mp3, frames, mp4) are not committed.

## Pipeline

All steps run in a work folder outside the repo (e.g. `$HOME\gcis-video`), so nothing generated can be committed by mistake.

| Step | Script | Run in | What it does |
|---|---|---|---|
| 1 | `tts_full.py [rate]` | work folder | Edge TTS, voice `zh-TW-HsiaoChenNeural`, rate `+4%`; writes `full/<seg>.mp3` and word timings to `full/words.json`. `SWAP` replaces polyphones with same-length homophones in the spoken text only (重來→蟲來, 重播→蟲播, 調閱→掉閱). |
| 2 | `durations.py` | work folder | Adds mp3 durations to `full/words.json`. |
| 3 | `record_demo.py` | work folder | Records s8–s11 of the real UI (`python main.py serve`, port 8000) at 1920×1080 / 30 fps through Playwright. Runs both party checks live before recording, blurs the dissolved company with injected CSS, captures the live citation verification and live party check in real time (CDP screencast). Writes `full/demo/frames/` and `full/demo/log.json`. |
| 4 | `build.py` | work folder | Copies `video.html` into `full/` and writes `full/data.js` and `full/demo/log.js`. |
| 5 | `render_full.py W K` | `full/` | Renders `video.html` at 60 fps (W workers, worker index K; resumable) and writes `timeline.json`. |
| 6 | `mix.py` | `full/` | Places each narration segment at its start time, writes `narration.m4a` and `LegalDebate_商業治理組影片.srt`. |

Final assembly:

```powershell
ffmpeg -y -framerate 60 -i frames/%05d.jpg -i narration.m4a -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -c:a copy -movflags +faststart LegalDebate_商業治理組影片.mp4
```

## The dissolved company

`record_demo.py` reads the BAN of the real dissolved limited company from the `DISSOLVED_BAN` environment variable, or from `dissolved_ban.txt` in the work folder. The BAN, name and address must never be written into the repo, subtitles or file names. Its name, BAN and address are blurred in every frame (`MASK_CSS`), and the video labels the query "示範查詢・與本案無關".

## Rules this video followed

- Debate content is a replay of recorded output and is labelled on screen ("錄製紀錄重播：先前由大型語言模型產生"); citation verification and the party check ran live during recording. If a wait is longer than 12 s, `record_demo.py` cuts it and `video.html` labels the cut with the skipped seconds. On 2026-10-04 verification finished in 4.1 s (16/16 passed), so nothing was cut.
- The party-check result is not shown or described as feeding into the debate; the architecture diagram only connects the fact layer to the pleading draft.
- The plaintiff field (TSMC) is labelled as a demonstration of a normal listed company, not a party to the case.
- Narration says "大型語言模型"; the architecture diagram names Claude (Anthropic). No school name, logo, advisor or team member names appear.
