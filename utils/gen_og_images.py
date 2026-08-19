#!/usr/bin/env python3
"""Pre-render one Open Graph card per post.

GitHub Pages runs Jekyll in safe mode and cannot generate images at build time,
so the cards are rendered here and committed. Run from the repository root:

    python3 utils/gen_og_images.py

Existing files are overwritten, so it is safe to re-run after editing a title.
"""
import glob, hashlib, os, re, sys
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG, FG, SUB, ACC, RULE = (24, 33, 46), (245, 247, 250), (156, 172, 192), (54, 138, 199), (44, 56, 74)
FONT = "/usr/share/fonts/google-noto-sans-cjk-vf-fonts/NotoSansCJK-VF.ttc"
OUT = "assets/images/og"
MARGIN, TOP = 90, 150

def font(size, weight):
    f = ImageFont.truetype(FONT, size, index=0)
    f.set_variation_by_name(weight)
    return f

def front_matter(path):
    t = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
    if not m:
        return {}
    d = {}
    for line in m.group(1).split("\n"):
        k = re.match(r"^([a-zA-Z_-]+):\s*(.*)$", line)
        if k:
            d[k.group(1)] = k.group(2).strip().strip('"').strip("'")
    return d

def tokens(text):
    """Break a title where it may wrap: between words in Latin, between
    characters in CJK. Runs of each script are separated first, otherwise a
    greedy word match swallows the CJK that follows it."""
    out = []
    for run in re.findall(r"[^\x00-\x7F]+|[\x00-\x7F]+", text):
        if ord(run[0]) > 127:
            out.extend(run)
        else:
            out.extend(re.findall(r"\S+\s*|\s+", run))
    return out

def wrap(draw, text, fnt, max_w):
    lines, cur = [], ""
    for tok in tokens(text):
        trial = cur + tok
        if draw.textlength(trial, font=fnt) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur.rstrip())
            cur = tok if tok.strip() else ""
    if cur.strip():
        lines.append(cur.rstrip())
    return lines

def render(title, lang, out_path):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 14, H], fill=ACC)

    # Shrink until the title fits three lines that each stay inside the margins.
    max_w = W - MARGIN * 2 - 14
    for size in (66, 60, 54, 48, 42, 38):
        f = font(size, "Bold")
        lines = wrap(d, title, f, max_w)
        if len(lines) <= 3 and all(d.textlength(l, font=f) <= max_w for l in lines):
            break
    lines = lines[:3]

    # Centre the title in the space above the rule so a one-line English title
    # does not sit in a field of empty pixels.
    lh = int(size * 1.4)
    rule_y = H - 190
    y = max(TOP - 60, (rule_y - lh * len(lines)) // 2)
    for line in lines:
        d.text((MARGIN, y), line, font=f, fill=FG)
        y += lh

    y = rule_y
    d.line([(MARGIN, y), (W - MARGIN, y)], fill=RULE, width=2)
    d.text((MARGIN, y + 34), "Masahiko Sawada", font=font(34, "Medium"), fill=FG)
    d.text((MARGIN, y + 82), "PostgreSQL major contributor & committer",
           font=font(26, "Regular"), fill=SUB)

    site = "masahikosawada.github.io"
    sf = font(26, "Regular")
    d.text((W - MARGIN - d.textlength(site, font=sf), y + 82), site, font=sf, fill=SUB)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    # Flat colour and antialiased text: a 64-colour palette is visually identical
    # here and roughly a third of the size, which matters across ~60 cards.
    img.quantize(colors=64, method=Image.MEDIANCUT, dither=Image.NONE).save(
        out_path, optimize=True)

def slug(path):
    """An ASCII-only, stable name for the card.

    Japanese post filenames would otherwise give the image a percent-encoded
    URL, and two of them contain a space. Card scrapers are less reliable with
    those, so the non-ASCII parts are dropped and a short digest of the original
    name keeps the result unique and reproducible.
    """
    base = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", os.path.basename(path)).rsplit(".", 1)[0]
    ascii_part = re.sub(r"-+", "-", re.sub(r"[^A-Za-z0-9]+", "-", base)).strip("-").lower()
    if ascii_part == base.lower():
        return ascii_part
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    return f"{ascii_part}-{digest}".strip("-") if ascii_part else digest

def main():
    posts = sorted(glob.glob("_posts/*/*.md"))
    if not posts:
        sys.exit("no posts found; run from the repository root")
    n = 0
    for p in posts:
        fm = front_matter(p)
        title = fm.get("title")
        if not title:
            print("  skip (no title):", p)
            continue
        lang = fm.get("lang", "en")
        out = f"{OUT}/{lang}/{slug(p)}.png"
        render(title, lang, out)
        n += 1
    print(f"{n} cards written under {OUT}/")

if __name__ == "__main__":
    main()
