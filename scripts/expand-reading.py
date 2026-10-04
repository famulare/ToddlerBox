"""Maintainer-only fetch of pinned licensed words/art; installed Reading is offline.

uv run python scripts/expand-reading.py --credits PATH_TO_PINNED_GCOMPRIS_LICENSE
Then uv run python scripts/build-reading.py --prepare-trims.
Original drawings are editable SVG; prepared media retain per-source licenses.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / "assets/reading"
REV = "5cfd4e4a4236701ec5e9d04a1796b6837d945403"
MOJI = "aeb8bb3a59e2de39c754ac79180c8131c906acea"
GROUPS = {
    "short_a_cvc": "bat rat fan bag jam ram can van tap rag ham",
    "short_e_cvc": "egg leg peg jet web",
    "short_i_cvc": "pin fin tin lid kid zip bin",
    "short_o_cvc": "box fox",
    "short_u_cvc": "nut hut cub jug gum tub pup bun cup rug mud bud",
    "digraphs": "cash ash dish shed shack shell bell hill doll well",
    "adjacent_consonants": "flag crab plug plum sled nest lamp milk mask desk pond sand ant belt stamp plant brush",
}
CODES = {"bat":"1F987", "rat":"1F400", "bag":"1F6CD", "ram":"1F40F", "van":"1F690",
         "ham":"1F356", "leg":"1F9B5", "jet":"2708", "pin":"1F4CC", "kid":"1F9D2",
         "bin":"1F5D1", "fox":"1F98A", "nut":"1F95C", "hut":"1F6D6", "cub":"1F43B",
         "tub":"1F6C1", "cup":"2615", "cash":"1F4B5",
         "dish":"1F37D", "shell":"1F41A", "bell":"1F514", "flag":"1F3F3",
         "crab":"1F980", "plug":"1F50C", "sled":"1F6F7", "nest":"1FAB9",
         "milk":"1F95B", "ant":"1F41C", "plant":"1FAB4", "brush":"1F58C"}
REUSE = {"egg":"egg", "web":"web", "box":"box", "pup":"dog", "rug":"mat", "shack":"hut"}
DRAWINGS = {
 "bun": '<path d="M90 300 Q85 125 256 125 Q427 125 422 300 Z" fill="#d5b487"/><path d="M90 300 Q100 385 256 385 Q412 385 422 300 Z" fill="#b6977d"/><path d="M180 175 L210 210 M245 160 L270 200 M310 175 L335 210"/>',
 "gum": '<rect x="90" y="210" width="225" height="115" rx="12" fill="#c193a0"/><path d="M110 235 H260 M110 270 H260"/><rect x="265" y="180" width="90" height="210" rx="12" fill="#fffdf5" transform="rotate(-15 310 285)"/><path d="M275 190 L340 170 M305 375 L365 355"/>',
 "fan": '<circle cx="256" cy="210" r="145"/><path d="M256 210 Q100 50 170 280 Q320 410 256 210 Q440 100 300 100 Q130 180 256 210"/><path d="M256 355 V440 M180 440 H330"/>',
 "jam": '<rect x="140" y="145" width="232" height="300" rx="30" fill="#c193a0"/><rect x="135" y="100" width="242" height="65" rx="15"/><rect x="170" y="220" width="172" height="130" fill="#fffdf5"/><path d="M210 260 Q256 200 302 260 Q256 355 210 260" fill="#d76d78"/>',
 "can": '<ellipse cx="256" cy="130" rx="110" ry="32"/><path d="M146 130 V385 Q256 460 366 385 V130"/><path d="M146 225 H366 M146 310 H366"/>',
 "tap": '<path d="M90 370 V310 H280 V210 H210 V145 H320 V230 H410 V295 H350"/><path d="M265 145 V85 M205 85 H325"/><path d="M390 330 Q430 390 390 425 Q350 390 390 330" fill="#8cc5cf"/>',
 "rag": '<path d="M110 150 L380 100 L435 350 L320 410 L95 365 Z" fill="#a6c4b4"/><path d="M140 190 L360 160 M150 240 L380 215 M175 300 L330 285"/>',
 "peg": '<path d="M195 110 L330 390 L290 410 L140 150 Z M330 110 L200 395 L150 380 L275 130 Z" fill="#d5b487"/><circle cx="235" cy="240" r="30"/>',
 "fin": '<path d="M70 290 Q190 140 395 230 L445 160 V355 L395 280 Q190 380 70 290 Z"/><path d="M180 230 L260 100 L305 230" fill="#8cc5cf"/><circle cx="115" cy="275" r="8" fill="#303a38"/>',
 "tin": '<ellipse cx="256" cy="130" rx="110" ry="32"/><path d="M146 130 V385 Q256 460 366 385 V130" fill="#cad3d5"/><ellipse cx="256" cy="130" rx="110" ry="32"/>',
 "lid": '<path d="M85 245 Q256 65 425 245 Z" fill="#cad3d5"/><path d="M100 275 V390 Q256 440 410 390 V275 M220 135 V90 H290 V135"/>',
 "zip": '<path d="M210 95 V430 M300 95 V430"/><path d="M220 100 H290 M220 140 H290 M220 180 H290 M220 220 H290 M220 260 H290 M220 300 H290 M220 340 H290"/><rect x="225" y="365" width="60" height="75" rx="15" fill="#a6c4b4"/>',
 "jug": '<path d="M130 120 H310 V175 L335 210 V375 Q250 450 150 380 V180 Z" fill="#8cc5cf"/><path d="M325 195 Q460 180 420 330 Q400 375 335 350"/>',
 "mud": '<path d="M90 300 Q25 180 180 190 Q210 80 320 175 Q490 130 440 305 Q470 415 320 405 Q180 455 90 300 Z" fill="#b6977d"/>',
 "bud": '<path d="M250 420 V275 M250 360 Q80 240 140 375 Q200 420 250 360" fill="#a6c4b4"/><path d="M250 295 Q90 160 210 90 Q230 200 255 190 Q270 150 300 85 Q410 200 250 295 Z" fill="#c193a0"/>',
 "ash": '<path d="M80 385 Q170 250 235 180 Q360 250 435 385 Z" fill="#c8cbc7"/><path d="M160 345 L200 270 M260 255 L310 325 M325 345 L365 365"/>',
 "shed": '<path d="M95 230 L256 95 L417 230 V420 H95 Z" fill="#d5b487"/><path d="M190 420 V245 H310 V420 M80 230 L256 85 L432 230"/>',
 "hill": '<path d="M55 420 Q135 330 180 190 Q230 105 275 170 Q355 315 455 420 Z" fill="#a6c4b4"/>',
 "doll": '<circle cx="256" cy="155" r="65" fill="#e5be99"/><path d="M220 220 L140 365 H370 L290 220 Z" fill="#c193a0"/><path d="M220 365 V425 M290 365 V425 M200 250 L120 290 M315 250 L390 290"/><circle cx="235" cy="150" r="5"/><circle cx="275" cy="150" r="5"/><path d="M235 185 Q255 200 280 185"/>',
 "well": '<ellipse cx="256" cy="310" rx="140" ry="55"/><path d="M116 310 V420 Q256 460 396 420 V310 M150 285 V145 M360 285 V145 M95 145 L256 60 L415 145 Z M256 155 V300"/><path d="M215 300 H295 V350 H215 Z" fill="#cad3d5"/>',
 "plum": '<path d="M250 140 Q390 110 385 290 Q390 425 245 435 Q95 395 125 230 Q140 130 250 140" fill="#a398bd"/><path d="M250 145 Q255 70 300 65 M265 110 Q370 70 365 130 Q300 180 265 110" fill="#a6c4b4"/>',
 "lamp": '<path d="M180 95 H330 L385 265 H125 Z" fill="#e1c68a"/><path d="M256 265 V420 M170 420 H340"/>',
 "mask": '<path d="M130 180 Q256 100 382 180 V315 Q256 420 130 315 Z" fill="#8cc5cf"/><path d="M130 180 Q15 180 75 300 Q100 330 130 315 M382 180 Q500 180 437 300 Q410 330 382 315 M170 230 H340 M170 275 H340"/>',
 "desk": '<path d="M90 200 H425 V270 H90 Z" fill="#d5b487"/><path d="M125 270 V425 M390 270 V425 M280 200 V270 M305 235 H365"/>',
 "pond": '<ellipse cx="245" cy="320" rx="190" ry="115" fill="#8cc5cf"/><path d="M145 270 H245 M245 330 H380 M95 360 H190 M375 230 V110 M405 240 V155 M350 220 V155"/>',
 "sand": '<path d="M70 410 Q160 300 250 225 Q345 275 440 410 Z" fill="#e1c68a"/><path d="M140 365 H170 M245 310 H280 M310 375 H340"/>',
 "belt": '<rect x="70" y="200" width="375" height="100" rx="28" fill="#b6977d"/><rect x="175" y="185" width="115" height="130" rx="10"/><path d="M205 250 H270"/><circle cx="340" cy="250" r="5"/><circle cx="390" cy="250" r="5"/>',
 "stamp": '<path d="M110 80 H405 V430 H110 Z" fill="#fffdf5" stroke-dasharray="18 10"/><rect x="145" y="125" width="225" height="260" fill="#8cc5cf"/><path d="M250 155 L275 240 L350 240 L290 280 L310 350 L250 310 L190 350 L210 280 L150 240 L225 240 Z" fill="#e1c68a"/>',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credits", type=Path, required=True)
    args = parser.parse_args()
    section = args.credits.read_text().split("./en_US/words:\n")[1].split("\n./")[0]
    credits = {line.split(".ogg ", 1)[0]: line.split(".ogg ", 1)[1] for line in section.splitlines() if ".ogg " in line}
    manifest = json.loads((ROOT / "sources.json").read_text())
    sources = {source["id"]: source for source in manifest["sources"]}
    words = json.loads((ROOT / "words.json").read_text())
    existing = {word["word"] for word in words}
    requests = []
    for group, names in GROUPS.items():
        for name in names.split():
            if name in existing or name not in credits:
                continue
            words.append({"word": name, "set": group, "units": re.findall("sh|ck|ll|ff|ss|gg|.", name)})
            requests.append({"id": "word-"+name, "source_url": f"https://invent.kde.org/education/gcompris-data/-/raw/{REV}/voices/en_US/words/{name}.ogg",
                             "revision": REV, "license": "GPL-3.0-or-later" if "GPL V3+" in credits[name] else "CC-BY-SA-3.0",
                             "credit": credits[name], "path": f"sources/word-{name}.ogg"})
    for word in words:
        name = word["word"]
        if name == "egg":
            word["units"] = ["e", "gg"]
        if name in {"bun", "gum"}:
            sources.pop("image-"+name, None)  # Replace ambiguous early illustrations.
        if "image-"+name in sources:
            continue
        if name in REUSE and "image-"+REUSE[name] in sources:
            old = sources["image-"+REUSE[name]]
            sources["image-"+name] = dict(old, id="image-"+name)
        elif name in CODES or REUSE.get(name) in CODES:
            code = CODES[name] if name in CODES else CODES[REUSE[name]]
            requests.append({"id":"image-"+name, "source_url":f"https://raw.githubusercontent.com/hfg-gmuend/openmoji/{MOJI}/color/svg/{code}.svg",
                             "revision": MOJI, "license":"CC-BY-SA-4.0", "credit":"OpenMoji contributors", "path":f"sources/image-{name}.svg"})
        elif name in DRAWINGS:
            data = ('<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512"><g fill="none" stroke="#303a38" stroke-width="14" stroke-linecap="round" stroke-linejoin="round">'+DRAWINGS[name]+'</g></svg>').encode()
            path = ROOT / f"sources/image-{name}.svg"
            path.write_bytes(data)
            sources["image-"+name] = {"id":"image-"+name,"source_url":"ToddlerBox original SVG", "revision":"2026-10-reading-expansion",
                                       "license":"MIT", "credit":"ToddlerBox original illustration", "path":str(path.relative_to(ROOT)), "sha256":hashlib.sha256(data).hexdigest()}
        else:
            raise ValueError("Missing picture for "+name)
    def fetch(source):
        path = ROOT / source["path"]
        if not path.exists():
            with urllib.request.urlopen(source["source_url"], timeout=40) as response:
                data = response.read(2_000_001)
            if len(data)>2_000_000:
                raise ValueError("Oversized source")
            path.write_bytes(data)
        source["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return source
    with ThreadPoolExecutor(max_workers=5) as pool:
        for source in pool.map(fetch, requests):
            sources[source["id"]] = source
    # 'shack' reuses the newly fetched hut, whose credit/bytes remain unchanged.
    if "image-shack" not in sources and "image-hut" in sources:
        sources["image-shack"] = dict(sources["image-hut"], id="image-shack")
    manifest["sources"] = list(sources.values())
    (ROOT / "sources.json").write_text(json.dumps(manifest,indent=2)+"\n")
    (ROOT / "words.json").write_text(json.dumps(words,indent=2)+"\n")
    expanded = sorted(source["id"][5:] for source in sources.values()
                      if source["id"].startswith("word-") and source.get("revision") == REV)
    (ROOT / "licenses/GCompris-expansion-credits.txt").write_text("Upstream voices/LICENSE at "+REV+"\n\n"+"\n".join(name+".ogg "+credits[name] for name in expanded)+"\n")
    print(f"Prepared sources for {len(words)} illustrated words; existing sources preserved.")


if __name__ == "__main__":
    main()
