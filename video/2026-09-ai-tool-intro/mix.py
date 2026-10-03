import json, subprocess
tl = json.load(open("timeline.json", encoding="utf-8"))
st, total = tl["start"], tl["total"]
order = ["s1","s2","s3","s4","s5","s6","s7","s8a","s8b","s9","s10","s11"]
args = ["ffmpeg", "-v", "error", "-y"]
for k in order: args += ["-i", f"{k}.mp3"]
fc = ";".join(f"[{i}]adelay={int(st[k]*1000)}|{int(st[k]*1000)}[a{i}]" for i, k in enumerate(order))
fc += ";" + "".join(f"[a{i}]" for i in range(len(order))) + f"amix=inputs={len(order)}:normalize=0,apad,atrim=0:{total:.3f}[out]"
args += ["-filter_complex", fc, "-map", "[out]", "-ar", "48000", "-c:a", "aac", "-b:a", "192k", "narration.m4a"]
subprocess.run(args, check=True)
def ts(t):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
bad = [s for s in tl["subs"] if s["t1"] <= s["t0"]]
with open("LegalDebate_作品影片.srt", "w", encoding="utf-8") as f:
    for i, s in enumerate(tl["subs"], 1): f.write(f"{i}\n{ts(s['t0'])} --> {ts(s['t1'])}\n{s['txt']}\n\n")
print("subs", len(tl["subs"]), "bad", bad, "total", round(total, 2))
