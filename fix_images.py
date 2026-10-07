"""Review and fix broken images in the coh2.win mirror.

The mirror saved missing images as .html files containing a 404 page, so
<img src=".../foo.html"> shows nothing. This script maps each broken path to a
real icon in sites/default/files/game_icons/ and lets you approve each mapping.

    python fix_images.py            review mappings (GUI), saves image_review.json
    python fix_images.py --redo     review again, including already decided ones
    python fix_images.py --apply    rewrite the .html files using approved mappings
    python fix_images.py --apply --only NAME   apply just the mappings whose path contains NAME

Review keys:
    1-8        select a candidate          Enter / y   approve selected
    n          reject (no matching icon)   s           skip (decide later)
    b / Left   go back                     q / Esc     save and quit
    Type in the search box and press Enter to search all icons by name.

Requires Pillow (pip install pillow).
"""

import argparse
import difflib
import html
import io
import json
import math
import os
import re
import sys
import tempfile
import threading
import urllib.request
import webbrowser
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ICON_DIR = "sites/default/files/game_icons"
REVIEW_FILE = ROOT / "image_review.json"
CACHE_DIR = Path(tempfile.gettempdir()) / "coh2win_wayback"
NUM_CANDIDATES = 8

IMG_RE = re.compile(r"<img\b[^>]*>", re.I | re.S)
SRC_RE = re.compile(r'\bsrc="(?:\.\./)*([^"?]+\.html)(\?[^"]*)?"', re.I)
ATTR_RE = re.compile(r'\b(title|alt|width|height)="([^"]*)"', re.I)

FACTIONS = [  # (keywords found in page path, regex that marks the faction in icon names)
    (("british", "britansk"), r"british"),
    (("us-forces", "amerikansk"), r"aef"),
    (("soviet", "sovetsk", "penal", "shtrafnoy"), r"soviet"),
    (("oberkommando", "okw", "zapad"), r"west_german"),
    (("wehrmacht", "vermakht"), r"(?<!west_)german"),
]
STOP = {"icons", "icon", "s", "big", "new", "preview", "png", "html", "the", "of", "and", "a"}


# ---------------------------------------------------------------- scanning

def html_files():
    for dirpath, _, files in os.walk(ROOT):
        if "game_icons" in dirpath or ".git" in dirpath:
            continue
        for f in files:
            if f.endswith(".html"):
                yield Path(dirpath) / f


def scan_broken():
    """Return {broken_path: info} for every <img> whose src points at a .html file."""
    found = defaultdict(lambda: {"titles": Counter(), "pages": [], "sizes": Counter(),
                                 "uses": 0, "query": None})
    for page in html_files():
        try:
            text = page.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel_page = page.relative_to(ROOT).as_posix()
        for tag in IMG_RE.findall(text):
            m = SRC_RE.search(tag)
            if not m:
                continue
            path = m.group(1)
            if not path.startswith("sites/"):
                continue
            info = found[path]
            info["uses"] += 1
            if m.group(2) and not info["query"]:
                info["query"] = m.group(2)
            attrs = {k.lower(): v for k, v in ATTR_RE.findall(tag)}
            for key in ("title", "alt"):
                if attrs.get(key, "").strip():
                    info["titles"][html.unescape(attrs[key].strip())] += 1
            if "width" in attrs and "height" in attrs:
                info["sizes"][f'{attrs["width"]}x{attrs["height"]}'] += 1
            if rel_page not in info["pages"]:
                info["pages"].append(rel_page)
    return dict(found)


def faction_of(pages):
    votes = Counter()
    for p in pages:
        for keys, pattern in FACTIONS:
            if any(k in p for k in keys):
                votes[pattern] += 1
                break
    return votes.most_common(1)[0][0] if votes else None


# ---------------------------------------------------------------- matching

def clean_name(path, has_query):
    """'.../1237088889_preview_Foo_s_portraiteb9d.html' -> 'Foo_s_portrait'"""
    name = os.path.basename(path)[:-len(".html")]
    name = re.sub(r"^\d+_preview_", "", name)
    if has_query:  # HTTrack appends a 4-hex hash when the URL had ?itok=
        name = re.sub(r"[0-9a-f]{4}$", "", name)
    return name


def exact_match(name, icons_lower):
    variants = [name, re.sub(r"(_\d+)+$", "", name)]
    variants += [re.sub(r"_female$", "", v) for v in variants]
    variants += [re.sub(r"-\d+$", "", v) for v in variants]
    for v in variants:
        hit = icons_lower.get(v.lower() + ".png")
        if hit:
            return hit
    return None


def tokens(text):
    return {t for t in re.split(r"[^a-z0-9]+", text.lower())
            if t and t not in STOP and not t.isdigit() and len(t) > 1}


_ICON_TOKENS = {}
_IDF = {}


def _index(icons):
    if not _ICON_TOKENS:
        df = Counter()
        for icon in icons:
            _ICON_TOKENS[icon] = tokens(icon)
            df.update(_ICON_TOKENS[icon])
        # rare words ("sandbags") count more than common ones ("ability")
        _IDF.update({t: math.log(len(icons) / n) for t, n in df.items()})


def rank_icons(query_text, name, faction, icons, limit=NUM_CANDIDATES):
    _index(icons)
    q = tokens(query_text)
    if not q:
        return []
    scored = []
    for icon in icons:
        low = icon.lower()
        itoks = _ICON_TOKENS[icon]
        score = 0.0
        for t in q:
            if t in itoks:
                score += _IDF[t]
            elif len(t) >= 3 and t in low:
                score += 1
        if score == 0:
            continue
        if faction and re.search(faction, low):
            score += 1.5
        scored.append((score, icon))
    # name similarity is slow, so only use it to order the best few
    scored.sort(key=lambda x: -x[0])
    best = [(score + difflib.SequenceMatcher(None, name.lower(), icon.lower()[:-4]).ratio(), icon)
            for score, icon in scored[:40]]
    best.sort(key=lambda x: (-x[0], x[1]))
    return [icon for _, icon in best[:limit]]


def search_icons(text, icons, faction, limit=NUM_CANDIDATES):
    words = [w for w in text.lower().split() if w]
    hits = [i for i in icons if all(w in i.lower() for w in words)]
    if faction:
        hits.sort(key=lambda i: (not re.search(faction, i.lower()), i))
    return hits[:limit]


def build_items():
    icons = sorted(p.name for p in (ROOT / ICON_DIR).iterdir() if p.suffix.lower() == ".png")
    icons_lower = {i.lower(): i for i in icons}
    items = []
    for path, info in scan_broken().items():
        name = clean_name(path, bool(info["query"]))
        faction = faction_of(info["pages"])
        exact = exact_match(name, icons_lower)
        titles = [t for t, _ in info["titles"].most_common(5)]
        if exact:
            cands = [exact] + [c for c in rank_icons(name, name, faction, icons) if c != exact]
        else:
            cands = rank_icons(name + " " + " ".join(titles), name, faction, icons)
        items.append({
            "path": path, "name": name, "exact": bool(exact), "faction": faction,
            "candidates": cands[:NUM_CANDIDATES], "titles": titles,
            "sizes": [s for s, _ in info["sizes"].most_common(2)],
            "uses": info["uses"], "pages": info["pages"], "query": info["query"],
        })
    # exact matches first (quick approvals), then by how often the image is used
    items.sort(key=lambda it: (not it["exact"], -it["uses"], it["path"]))
    return items, icons


# ---------------------------------------------------------------- review file

def load_review():
    if REVIEW_FILE.exists():
        return json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
    return {}


def save_review(review):
    tmp = REVIEW_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(review, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(REVIEW_FILE)


# ---------------------------------------------------------------- wayback

def wayback_urls(item):
    """Guess the original coh2.win URL(s) of a broken image."""
    stem = item["path"][:-len(".html")]
    if item["query"]:
        stem = re.sub(r"[0-9a-f]{4}$", "", stem)
    query = item["query"] or ""
    for ext in (".png", ".jpg", ".jpeg", ".gif"):
        yield f"https://web.archive.org/web/2022id_/https://coh2.win/{stem}{ext}{query}"


def fetch_original(item):
    """Return image bytes from the Wayback Machine, or an error string."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / re.sub(r"[^A-Za-z0-9_.-]", "_", item["path"])
    if cache.exists():
        data = cache.read_bytes()
        return data if data else "not archived"
    last = "not archived"
    for url in wayback_urls(item):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "coh2win-image-review"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.headers.get_content_type().startswith("image/"):
                    data = r.read()
                    cache.write_bytes(data)
                    return data
        except urllib.error.HTTPError as e:
            if e.code != 404:
                return f"Wayback error {e.code}"
        except Exception as e:  # network down, timeout, ...
            return f"Wayback unavailable ({type(e).__name__})"
    cache.write_bytes(b"")
    return last


# ---------------------------------------------------------------- GUI

def run_review(redo, use_wayback):
    import tkinter as tk
    from tkinter import ttk
    from PIL import Image, ImageTk

    items, icons = build_items()
    review = load_review()
    queue = [it for it in items if redo or review.get(it["path"], {}).get("status") in (None, "skipped")]
    if not queue:
        print(f"Nothing left to review ({len(items)} broken images, all decided in {REVIEW_FILE.name}).")
        return

    root = tk.Tk()
    root.title("coh2.win image review")
    root.geometry("1150x760")
    try:
        root.state("zoomed")
    except tk.TclError:
        pass
    blank = tk.PhotoImage(width=1, height=1)  # lets image-less Labels be sized in pixels

    state = {"i": 0, "cands": [], "sel": 0, "photos": [], "orig_photo": None, "token": 0}

    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    progress = ttk.Label(top, font=("Segoe UI", 11, "bold"))
    progress.pack(side="left")
    counts = ttk.Label(top)
    counts.pack(side="right")

    info = ttk.Frame(root, padding=(8, 0))
    info.pack(fill="x")
    left = ttk.Frame(info)
    left.pack(side="left", fill="x", expand=True, anchor="n")
    path_lbl = ttk.Label(left, font=("Consolas", 10), wraplength=820, justify="left")
    path_lbl.pack(anchor="w")
    title_lbl = ttk.Label(left, font=("Segoe UI", 16, "bold"), wraplength=820, justify="left")
    title_lbl.pack(anchor="w", pady=(6, 0))
    meta_lbl = ttk.Label(left, wraplength=820, justify="left")
    meta_lbl.pack(anchor="w", pady=(4, 0))
    pages_lbl = ttk.Label(left, foreground="#555", wraplength=820, justify="left")
    pages_lbl.pack(anchor="w", pady=(2, 0))
    ttk.Button(left, text="Open a page that uses it", command=lambda: open_page()).pack(anchor="w", pady=6)

    sel_box = ttk.LabelFrame(info, text="Your choice (will replace it)", padding=6)
    sel_box.pack(side="right", anchor="n", padx=(6, 0))
    sel_img = tk.Label(sel_box, image=blank, width=160, height=160, bg="#222")
    sel_img.pack()
    sel_name = ttk.Label(sel_box, wraplength=180, justify="center", font=("Segoe UI", 9, "bold"))
    sel_name.pack()

    orig_box = ttk.LabelFrame(info, text="Original (Wayback Machine)", padding=6)
    orig_box.pack(side="right", anchor="n")
    orig_img = tk.Label(orig_box, image=blank, width=160, height=160, bg="#222")
    orig_img.pack()
    orig_status = ttk.Label(orig_box, wraplength=180, justify="center")
    orig_status.pack()

    search_row = ttk.Frame(root, padding=8)
    search_row.pack(fill="x")
    ttk.Label(search_row, text="Search icons:").pack(side="left")
    search_var = tk.StringVar()
    search = ttk.Entry(search_row, textvariable=search_var, width=50)
    search.pack(side="left", padx=6)
    ttk.Button(search_row, text="Search", command=lambda: do_search()).pack(side="left")
    ttk.Button(search_row, text="Suggested", command=lambda: show_candidates(cur()["candidates"])).pack(side="left", padx=6)

    # pack the bottom rows first so they stay visible even if the window is small
    buttons = ttk.Frame(root, padding=8)
    buttons.pack(side="bottom", fill="x")
    ttk.Label(root, padding=(8, 0), foreground="#555",
              text="Click an icon (or press 1-8) to pick it, then Approve (Enter).  "
                   "None fits? Search for one, or Reject (n).  Unsure? Skip (s).").pack(side="bottom", fill="x")

    grid = tk.Frame(root, padx=8)
    grid.pack(fill="both", expand=True)
    ttk.Button(buttons, text="◀ Back (b)", command=lambda: go_back()).pack(side="left")
    ttk.Button(buttons, text="Save & quit (q)", command=lambda: quit_()).pack(side="right")
    ttk.Button(buttons, text="Skip (s)", command=lambda: decide("skipped")).pack(side="right", padx=4)
    ttk.Button(buttons, text="Reject – no match (n)", command=lambda: decide("rejected")).pack(side="right", padx=4)
    ttk.Button(buttons, text="✔ Approve selected (Enter)", command=lambda: decide("approved")).pack(side="right", padx=4)

    def cur():
        return queue[state["i"]]

    def thumb(path, box):
        im = Image.open(path).convert("RGBA")
        scale = min(box / im.width, box / im.height, 3)
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
        return ImageTk.PhotoImage(im)

    def show_candidates(cands):
        state["cands"], state["sel"], state["photos"] = cands, 0, []
        prev = review.get(cur()["path"], {}).get("icon")
        if prev in cands:
            state["sel"] = cands.index(prev)
        for w in grid.winfo_children():
            w.destroy()
        if not cands:
            tk.Label(grid, text="No candidates – try the search box, or reject (n).",
                     font=("Segoe UI", 12)).grid(row=0, column=0, pady=40)
            highlight()
            return
        for n, icon in enumerate(cands):
            cell = tk.Frame(grid, bd=3, relief="flat", padx=4, pady=4)
            cell.grid(row=n // 4, column=n % 4, padx=4, pady=4, sticky="n")
            photo = thumb(ROOT / ICON_DIR / icon, 140)
            state["photos"].append(photo)
            img = tk.Label(cell, image=photo, bg="#222", width=150, height=150)
            img.pack()
            txt = tk.Label(cell, text=f"{n + 1}. {icon[:-4]}", wraplength=250, font=("Segoe UI", 8))
            txt.pack()
            for w in (cell, img, txt):
                w.bind("<Button-1>", lambda e, n=n: select(n))
                w.bind("<Double-Button-1>", lambda e, n=n: (select(n), decide("approved")))
        highlight()

    def highlight():
        for n, cell in enumerate(grid.winfo_children()):
            if isinstance(cell, tk.Frame):
                cell.configure(bg="#2e7d32" if n == state["sel"] else root.cget("bg"))
        if state["cands"]:
            icon = state["cands"][state["sel"]]
            state["sel_photo"] = thumb(ROOT / ICON_DIR / icon, 150)
            sel_img.configure(image=state["sel_photo"])
            sel_name.configure(text=icon[:-4])
        else:
            sel_img.configure(image=blank)
            sel_name.configure(text="(nothing selected)")

    def select(n):
        if 0 <= n < len(state["cands"]):
            state["sel"] = n
            highlight()

    def do_search():
        text = search_var.get().strip()
        if text:
            show_candidates(search_icons(text, icons, cur()["faction"]))
        root.focus_set()

    def open_page():
        webbrowser.open((ROOT / cur()["pages"][0]).as_uri())

    def load_original(item):
        state["token"] += 1
        token = state["token"]
        orig_img.configure(image=blank, text="")
        if not use_wayback:
            orig_status.configure(text="disabled (--no-wayback)")
            return
        orig_status.configure(text="looking up…")

        def work():
            result = fetch_original(item)
            root.after(0, lambda: show_original(token, result))
        threading.Thread(target=work, daemon=True).start()

    def show_original(token, result):
        if token != state["token"]:
            return
        if isinstance(result, str):
            orig_status.configure(text=result)
            return
        try:
            im = Image.open(io.BytesIO(result)).convert("RGBA")
            scale = min(150 / im.width, 150 / im.height, 3)
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
            state["orig_photo"] = ImageTk.PhotoImage(im)
            orig_img.configure(image=state["orig_photo"])
            orig_status.configure(text="found")
        except Exception:
            orig_status.configure(text="archived file is not an image")

    def show():
        it = cur()
        done = Counter(v["status"] for v in review.values())
        progress.configure(text=f"{state['i'] + 1} / {len(queue)}"
                                + ("   — exact name match" if it["exact"] else "   — suggested by similarity"))
        counts.configure(text=f"approved {done['approved']}   rejected {done['rejected']}   skipped {done['skipped']}")
        path_lbl.configure(text=it["path"] + (it["query"] or ""))
        title_lbl.configure(text=" / ".join(it["titles"]) or "(no title text)")
        prev = review.get(it["path"])
        meta = [f"Used {it['uses']}× on {len(it['pages'])} page(s)",
                f"display size {', '.join(it['sizes']) or '?'}",
                f"faction guess: {(it['faction'] or '?').replace('(?<!west_)', '')}"]
        if prev:
            meta.append(f"previous decision: {prev['status']}" + (f" → {prev.get('icon')}" if prev.get("icon") else ""))
        meta_lbl.configure(text="   ·   ".join(meta))
        pages_lbl.configure(text="e.g. " + ", ".join(it["pages"][:3]))
        search_var.set("")
        show_candidates(it["candidates"])
        load_original(it)

    def decide(status):
        it = cur()
        entry = {"status": status, "titles": it["titles"], "uses": it["uses"]}
        if status == "approved":
            if not state["cands"]:
                return
            entry["icon"] = state["cands"][state["sel"]]
        review[it["path"]] = entry
        save_review(review)
        if state["i"] + 1 < len(queue):
            state["i"] += 1
            show()
        else:
            quit_()

    def go_back():
        if state["i"] > 0:
            state["i"] -= 1
            show()

    def quit_():
        save_review(review)
        root.destroy()

    def on_key(e):
        if root.focus_get() is search:
            if e.keysym == "Return":
                do_search()
            elif e.keysym == "Escape":
                root.focus_set()
            return
        k = e.keysym
        if k in ("Return", "y"):
            decide("approved")
        elif k == "n":
            decide("rejected")
        elif k == "s":
            decide("skipped")
        elif k in ("b", "Left"):
            go_back()
        elif k in ("q", "Escape"):
            quit_()
        elif k.isdigit() and k != "0":
            select(int(k) - 1)
        elif k == "slash":
            search.focus_set()

    root.bind("<Key>", on_key)
    root.protocol("WM_DELETE_WINDOW", quit_)
    show()
    root.mainloop()

    done = Counter(v["status"] for v in review.values())
    print(f"Saved {REVIEW_FILE.name}: {dict(done)}  ({len(items)} broken images total)")


# ---------------------------------------------------------------- apply

def apply_review(only=None):
    review = load_review()
    mapping = {p: v["icon"] for p, v in review.items() if v.get("status") == "approved" and v.get("icon")}
    if only:
        mapping = {p: i for p, i in mapping.items() if only in p}
    if not mapping:
        print("No approved mappings" + (f" matching {only!r}" if only else ""), "in", REVIEW_FILE.name)
        return
    # work on bytes so encoding and CRLF line endings stay exactly as they are
    pattern = re.compile(("(" + "|".join(re.escape(p) for p in sorted(mapping, key=len, reverse=True))
                          + r""")(\?itok=[A-Za-z0-9_-]*)?(?=["'\s)])""").encode())
    changed_files = replacements = 0
    for page in html_files():
        data = page.read_bytes()
        new, n = pattern.subn(lambda m: f"{ICON_DIR}/{mapping[m.group(1).decode()]}".encode(), data)
        if n:
            page.write_bytes(new)
            changed_files += 1
            replacements += n
    print(f"Applied {len(mapping)} mappings: {replacements} replacements in {changed_files} files.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="rewrite html files with approved mappings")
    ap.add_argument("--redo", action="store_true", help="review already decided images again")
    ap.add_argument("--no-wayback", action="store_true", help="don't look up originals on the Wayback Machine")
    ap.add_argument("--only", metavar="TEXT", help="with --apply: only apply mappings whose broken path contains TEXT")
    args = ap.parse_args()
    if args.apply:
        apply_review(args.only)
    else:
        run_review(args.redo, not args.no_wayback)
