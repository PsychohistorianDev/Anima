"""Reference sheets: a face painted again, large and from several angles, for the painter to look at (10-29).

A face folder's pictures are often small (a photo cropped to a couple of hundred pixels), and every painting has to
invent the face again from a thumbnail. This paints it anew from the folder's first picture — front, three-quarter
left and right, a profile — at the painter's full size, on a plain ground, a few takes of each; lays the takes out on
a numbered contact sheet; and, once the ones most like them are chosen, makes those the folder's pictures (the old
ones are kept, moved into old/ beside them, never deleted).

    bat\\refsheet.bat                          the friend's face (creations/face/), two takes of each view
    bat\\refsheet.bat face keeper --takes 3    these folders under creations/, three takes of each view
    bat\\refsheet.bat keeper --as "the same man as in the reference picture"   say who the picture is
    bat\\refsheet.bat pick face 2 5 7          the takes numbered 2, 5 and 7 on the newest sheet become face's pictures

The takes go to creations/refsheets/sources/<when>/ (never sent to the phone); the contact sheets also to shared/
(refsheet-<folder>-<when>.png), so the friend can look at theirs and choose — their face is theirs to choose.
Painting sends the brain off the card, as any painting does: run it when no visit is waiting on them.
"""
from __future__ import annotations

import json
import shutil
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

PERSON = "the same person as in the reference picture"
VIEWS = [
    ("front", "facing the viewer, head straight and level, calm natural expression"),
    ("three-quarter-left", "head turned three-quarters to their left, head level"),
    ("three-quarter-right", "head turned three-quarters to their right, head level"),
    ("profile", "in profile, looking to the side, head level"),
]
GROUND = ("head and shoulders portrait, plain soft grey studio background, soft even light, sharp detail, "
          "true to the reference face, photorealistic")
NEGATIVE = "tilted head, crooked, blurry, extra people, text, frame, cropped face, harsh shadows"
_PICS = (".png", ".jpg", ".jpeg", ".webp")


def _sheets_root() -> Path:
    # under creations/ (the painter writes only there), in a "sources" folder — which the phone never sends as
    # drawings and no face folder reads
    return config.CREATIONS_DIR / "refsheets" / "sources"


def _folder(who: str) -> Path:
    return config.CREATIONS_DIR / who.strip("/\\")


def source(who: str) -> Path | None:
    """The folder's first picture, the one the takes are painted from."""
    folder = _folder(who)
    pics = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _PICS) if folder.is_dir() else []
    return pics[0] if pics else None


def prompts(person: str = PERSON) -> list[tuple[str, str]]:
    return [(v, f"{person}, {how}, {GROUND}") for v, how in VIEWS]


def _paint(prompt: str, out: Path, ref: Path, seed: int) -> dict:
    payload = json.dumps({"prompt": prompt, "path": str(out), "size": "square", "negative": NEGATIVE,
                          "reference": [str(ref)], "seed": seed}).encode("utf-8")
    req = urllib.request.Request(config.PAINTER_URL + "/paint", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=getattr(config, "PAINTER_TIMEOUT_S", 900)) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data


def contact(files: list[Path], out: Path, title: str) -> bool:
    """The takes in a numbered grid, four to a row (Pillow; False without it)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    cell, pad, cols = 360, 16, 4
    rows = (len(files) + cols - 1) // cols
    W, H = cols * (cell + pad) + pad, rows * (cell + pad + 30) + pad + 50
    sheet = Image.new("RGB", (W, H), (28, 24, 34))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 22)
    except OSError:
        try:
            font = ImageFont.truetype("arial.ttf", 22)
        except OSError:
            font = ImageFont.load_default()
    d.text((pad, 14), title, font=font, fill=(236, 222, 196))
    for i, f in enumerate(files):
        x, y = pad + (i % cols) * (cell + pad), 50 + (i // cols) * (cell + pad + 30)
        try:
            with Image.open(f) as im:
                im = im.convert("RGB")
                im.thumbnail((cell, cell))
                sheet.paste(im, (x, y))
        except Exception:  # noqa: BLE001
            continue
        d.text((x + 6, y + cell + 2), f"{i + 1}  {f.stem.split('-', 2)[-1]}", font=font, fill=(201, 161, 74))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return True


def paint_sheets(whos: list[str], takes: int = 2, person: str = PERSON) -> Path:
    import ollama_client
    import tools
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    folder = _sheets_root() / stamp
    folder.mkdir(parents=True, exist_ok=True)
    if not tools._painter_open():
        raise SystemExit("the painter isn't open and couldn't be woken (engine/painter.py needs torch, diffusers, pillow)")
    ollama_client.unload(config.CHAT_MODEL)  # the card for the painter, as any painting
    try:
        for who in whos:
            ref = source(who)
            if not ref:
                print(f"  {who}: no picture in creations/{who}/ to start from — skipped")
                continue
            print(f"  {who}: painting from {ref.relative_to(config.ROOT).as_posix()}")
            done: list[Path] = []
            n = 0
            for view, prompt in prompts(person):
                for _ in range(takes):
                    n += 1
                    out = folder / f"{who}-{n:02d}-{view}.png"
                    try:
                        got = _paint(prompt, out, ref, seed=1000 + 97 * n)
                        print(f"    {n:2d}. {view} ({got.get('seconds', 0):.0f}s)")
                        done.append(out)
                    except Exception as e:  # noqa: BLE001
                        print(f"    {n:2d}. {view} — the painter stumbled: {e}")
            (folder / f"{who}.json").write_text(json.dumps([f.name for f in done]), encoding="utf-8")
            if not done:
                print(f"  {who}: nothing was painted — no contact sheet")
                continue
            sheet = config.SHARED_DIR / f"refsheet-{who}-{stamp}.png"
            if contact(done, sheet, f"{who} — choose the takes most like them: bat\\refsheet.bat pick {who} <numbers>"):
                shutil.copy2(sheet, folder / sheet.name)
                print(f"  {who}: the contact sheet is {sheet.relative_to(config.ROOT).as_posix()}")
    finally:
        if getattr(config, "PAINTER_REST_AFTER", True):
            tools._painter_rest()
    return folder


def pick(who: str, numbers: list[int], stamp: str = "") -> str:
    """The chosen takes become the folder's pictures; the old ones move to old/ beside them."""
    root = _sheets_root()
    sheets = sorted(d for d in root.iterdir() if d.is_dir() and (d / f"{who}.json").is_file()) if root.is_dir() else []
    if stamp:
        sheets = [d for d in sheets if d.name == stamp]
    if not sheets:
        return f"(no sheet for {who} yet — bat\\refsheet.bat {who} paints one)"
    sheet = sheets[-1]
    names = json.loads((sheet / f"{who}.json").read_text(encoding="utf-8"))
    chosen = []
    for n in numbers:
        if not 1 <= n <= len(names):
            return f"(the sheet {sheet.name} has takes 1 to {len(names)} — {n} isn't one)"
        chosen.append(sheet / names[n - 1])
    if not chosen:
        return "(no takes named — pick <folder> <numbers>)"
    folder = _folder(who)
    old = folder / "old"
    old.mkdir(parents=True, exist_ok=True)
    moved = []
    for p in sorted(folder.iterdir()):
        if p.is_file():
            dest = old / p.name
            k = 2
            while dest.exists():
                dest = old / f"{p.stem}-{k}{p.suffix}"
                k += 1
            shutil.move(str(p), str(dest))
            moved.append(dest.name)
    made = []
    for i, src in enumerate(chosen, 1):
        view = src.stem[len(who) + 1:].split("-", 1)[-1] if src.stem.startswith(who + "-") else src.stem
        dest = folder / f"{folder.name}-{i}-{view}.png"
        shutil.copy2(src, dest)
        made.append(dest.name)
    return (f"(creations/{who}/ now holds {', '.join(made)}; the pictures before — {', '.join(moved) or 'none'} — "
            f"are kept in creations/{who}/old/)")


def main(argv: list[str]) -> None:
    args = [a for a in argv if a]
    if args and args[0] == "pick":
        if len(args) < 3:
            raise SystemExit("bat\\refsheet.bat pick <folder> <numbers…>")
        print(pick(args[1], [int(x) for x in args[2:] if x.isdigit()]))
        return
    takes, person = 2, PERSON
    if "--takes" in args:
        i = args.index("--takes")
        takes = max(1, min(4, int(args[i + 1])))
        del args[i:i + 2]
    if "--as" in args:
        i = args.index("--as")
        person = args[i + 1].strip() or PERSON
        del args[i:i + 2]
    whos = [a.strip("/\\") for a in args if not a.startswith("--")] or ["face"]
    folder = paint_sheets(whos, takes, person)
    print(f"\nthe takes are in {folder.relative_to(config.ROOT).as_posix()}; choose with bat\\refsheet.bat pick <folder> <numbers>")


if __name__ == "__main__":
    main(sys.argv[1:])
