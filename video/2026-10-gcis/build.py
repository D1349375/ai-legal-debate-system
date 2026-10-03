"""Prepare the render folder: copy video.html next to the narration and recording, and write data.js / demo/log.js.
Run in the work folder (the one that contains full/)."""
import json, pathlib, shutil
here = pathlib.Path(__file__).resolve().parent
full = pathlib.Path("full")
shutil.copy(here / "video.html", full / "video.html")
(full / "data.js").write_text("window.DATA = " + (full / "words.json").read_text(encoding="utf-8") + ";\n", encoding="utf-8")
(full / "demo" / "log.js").write_text("window.LOG = " + (full / "demo" / "log.json").read_text(encoding="utf-8") + ";\n", encoding="utf-8")
print("ready:", (full / "video.html").resolve())
