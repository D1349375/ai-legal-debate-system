"""Full-video narration (s1–s13 of narration.md). Run in the work folder; writes full/<seg>.mp3 and full/words.json.
`text` is what subtitles show; TTS gets same-length homophone swaps for polyphones."""
import asyncio, json, pathlib, sys
import edge_tts

VOICE = "zh-TW-HsiaoChenNeural"
RATE = sys.argv[1] if len(sys.argv) > 1 else "+4%"
# 重 read as chóng; 調 read as diào; 關卡's 卡 read as kǎ (佧 has only that reading);
# 短少 read as shǎo (a space before 的 stops TTS from reading 少 as shào).
SWAP = {"重來": "蟲來", "重播": "蟲播", "調閱": "掉閱", "關卡": "關佧", "短少的": "短少 的"}

SEGMENTS = [
 ("s1", "律師一天工作八小時，真正能向客戶計費的，只有兩到三小時。檢索判決、盤點爭點、推演對造攻防、草擬書狀，每個案子都要重來一次。"),
 ("s2", "生成式AI看似能分擔，但美國已有律所把AI捏造的判決寫進書狀，遭法院裁罰。企業案件還多一道關卡：對造公司若已解散，該列誰代表公司，公示資料不會告訴你。"),
 ("s3", "LegalDebate由大型語言模型分別扮演原告、被告代理人與法官，從檢索、攻防推演到訴狀骨架，一次跑完；當事人另以商工登記查核。每筆引用、每個當事人，都比對官方來源。"),
 ("s4", "靠的是四個關鍵。第一，真對抗，而非換人設：雙方用立場驅動檢索詞，各自獨立檢索、盲測提出主張；法官每題訊問都須標註依據。"),
 ("s5", "第二，彙整不交給AI：雙方弱點與立場漂移，由確定性演算法計算。"),
 ("s6", "第三，零容忍引用閘門：法條比對全國法規資料庫，判決比對1088份最高法院判決，並即時查詢司法院；未通過，就拒絕寫入。"),
 ("s7", "第四，官方事實層：當事人以統編查詢商工登記開放資料，由確定性規則轉成程序警示。"),
 ("s8", "以一件200萬元貨款未付的案件示範，畫面是先前由大型語言模型產生的攻防紀錄重播。法官追問被告：短少的究竟是哪些零件？"),
 ("s9", "按下查證，16筆引用即時比對官方來源，全數通過。"),
 ("s10", "訴狀骨架同步產出，訴之聲明、事實及理由都已排好；上方的當事人資料，則來自商工登記即時查核。"),
 ("s11", "假設對造已解散，我們以一家實際已解散的有限公司示範，名稱已遮蔽，與本案無關。系統警示：法定代理人應列清算人，有限公司原則上為全體股東，並提示調閱解散前的變更登記表。實務上就有人誤認已廢止的公司沒有法定代理人，遭法院駁回。"),
 ("s12", "四件測試案件74筆引用中，73筆通過查證，1筆捏造字號當場攔截；判決中的300家當事人公司，有3%目前已解散、廢止或合併等。"),
 ("s13", "律師拿到的不再是一張白紙，而是一份攻防過、查證過的起點。產出仍須律師審核。LegalDebate，讓每一筆引用、每一個當事人，都經得起查證。"),
]


async def run(key, text):
    spoken = text
    for a, b in SWAP.items():
        assert len(a) == len(b.replace(" ", "")); spoken = spoken.replace(a, b)
    comm = edge_tts.Communicate(spoken, VOICE, rate=RATE, boundary="WordBoundary")
    words = []
    with open(f"full/{key}.mp3", "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                w = chunk["text"]
                for a, b in SWAP.items():
                    w = w.replace(b, a) if b in w else w.replace(b[0], a[0]) if b[0] in w else w
                words.append({"t": chunk["offset"] / 1e7, "d": chunk["duration"] / 1e7, "w": w})
    return words


async def main():
    pathlib.Path("full").mkdir(exist_ok=True)
    only = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    out = json.load(open("full/words.json", encoding="utf-8")) if only else {}
    for k, v in SEGMENTS:
        if only and k not in only: continue
        out[k] = {"text": v, "words": await run(k, v), "rate": RATE}
    json.dump(out, open("full/words.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


asyncio.run(main())
