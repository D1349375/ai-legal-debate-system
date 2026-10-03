"""Full-video narration. `text` is what subtitles show; TTS gets same-length homophone swaps for polyphones."""
import asyncio, json, sys
import edge_tts

VOICE = "zh-TW-HsiaoChenNeural"
RATE = sys.argv[1] if len(sys.argv) > 1 else "+4%"
SWAP = {"重來": "蟲來", "重播": "蟲播"}  # 重 read as chóng

SEGMENTS = [
 ("s1", "律師一天工作八小時，真正能向客戶計費的，只有兩到三小時。而檢索判決、盤點爭點、推演對造攻防、草擬書狀初稿，這些繁瑣的文書工作，每個案子都要重來一次。"),
 ("s2", "生成式AI看似能分擔。但2023年，美國一家律所把ChatGPT捏造的六件判決寫進書狀，遭法院裁罰；2025年加州一起上訴案，23段引文，有21段查無原文。"),
 ("s3", "結果是：AI寫出來的東西，律師還得一條條手動查證；單一模型只站一個立場，對造會怎麼攻擊，還是得自己想。時間，根本沒省下來。"),
 ("s4", "LegalDebate，讓律師真正把這些繁瑣工作交出去。由大型語言模型分別扮演原告、被告代理人與法官，從檢索、盤點爭點、攻防推演到訴狀骨架，一次跑完；每條引用自動比對官方來源，不必再逐條手查。"),
 ("s5", "能放心交出去，靠三個技術關鍵。第一，真對抗，而非換人設：原告與被告用立場驅動檢索詞，各自獨立檢索、盲測提出主張，法官每題訊問都須標註依據。第二，彙整不交給AI：雙方弱點與立場漂移，由確定性演算法計算。第三，零容忍引用閘門：引用預設不存在；法條比對全國法規資料庫，判決比對1088份最高法院判決，並即時查詢司法院，未通過，就在資料庫層拒絕寫入。"),
 ("s6", "我們用最高法院114年度台上字第1547號的雙方主張做測試，不提供法院見解。畫面是當時由LLM產生的攻防紀錄重播。"),
 ("s7", "法官第四題追問：每坪75萬元的抵償單價，是否經兩造合意？這正是該案被發回更審的核心爭點。"),
 ("s8a", "按下查證，25條引用即時比對官方來源，十幾秒內跑完。"),
 ("s8b", "24條通過；原告引用的最高法院105年度台簡上字第33號，查無此案號，直接攔截。而原告在辯論終結時，也已主動撤回這筆引用。"),
 ("s9", "機械彙整當場算出雙方立場漂移：原告0.3158，被告0.35。"),
 ("s10", "訴狀骨架同步產出，訴之聲明、金額利息、事實及理由都已排好。這次實測，從案件建立到骨架產出，約43分鐘。"),
 ("s11", "律師拿到的不再是一張白紙，而是一份已經攻防過、查證過的起點。產出仍須律師審核；依律師法第127條，我們只做事務所內部工具。讓AI扛下繁瑣，律師專心判斷。"),
]


async def run(key, text):
    spoken = text
    for a, b in SWAP.items():
        assert len(a) == len(b); spoken = spoken.replace(a, b)
    comm = edge_tts.Communicate(spoken, VOICE, rate=RATE, boundary="WordBoundary")
    words = []
    with open(f"full/{key}.mp3", "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                w = chunk["text"]
                for a, b in SWAP.items():
                    w = w.replace(b[0], a[0]) if b[0] in w else w
                words.append({"t": chunk["offset"] / 1e7, "d": chunk["duration"] / 1e7, "w": w})
    return words


async def main():
    only = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    out = json.load(open("full/words.json", encoding="utf-8")) if only else {}
    for k, v in SEGMENTS:
        if only and k not in only: continue
        out[k] = {"text": v, "words": await run(k, v), "rate": RATE}
    json.dump(out, open("full/words.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


asyncio.run(main())
