"""Attach mp3 durations to full/words.json and print the total."""
import json, subprocess

d = json.load(open("full/words.json", encoding="utf-8"))
for k in d:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f"full/{k}.mp3"],
                         capture_output=True, text=True).stdout
    d[k]["dur"] = float(out)
json.dump(d, open("full/words.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print({k: round(v["dur"], 2) for k, v in d.items()})
print("sum", round(sum(v["dur"] for v in d.values()), 1))
