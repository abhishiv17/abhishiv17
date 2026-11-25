#!/usr/bin/env python3
"""BUG SLAYER — a community roguelike that lives on a GitHub profile.

Every visitor move is a GitHub issue titled `bugslayer|<dir>`. A workflow runs
this script, which plays all open move issues in order, redraws the board SVG
and the README, and (with --close) comments on and closes the issues.
Standard library only.
"""
import json, os, random, re, subprocess, sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
STATE = os.path.join(HERE, "state.json")
PENDING = os.path.join(HERE, ".pending.json")
README = os.path.join(ROOT, "README.md")
BOARD = os.path.join(ROOT, "assets", "game", "board.svg")
GLYPHS = json.load(open(os.path.join(HERE, "glyphs.json")))

REPO = os.environ.get("GITHUB_REPOSITORY", "abhishiv17/abhishiv17")
OWNER = REPO.split("/")[0]
COLS, ROWS, TILE = 13, 9, 56
MAXHP = 5
DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
ARROW = {"up": "⬆️", "down": "⬇️", "left": "⬅️", "right": "➡️"}

INK, INK2, LINE = "#131210", "#1b1916", "#2f2b26"
PAPER, PAPER2, MUTED = "#f1eadb", "#cfc6b5", "#8f8677"
RED, GREEN, YELLOW, BLUE, PEACH = "#ff5a47", "#22a06b", "#ffd23f", "#afbdff", "#f7a27a"


# ------------------------------------------------------------------ world
def bfs(start, walls):
    seen, q = {start}, deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in DIRS.values():
            n = (x + dx, y + dy)
            if n not in seen and n not in walls and 0 < n[0] < COLS - 1 and 0 < n[1] < ROWS - 1:
                seen.add(n)
                q.append(n)
    return seen


def new_level(s):
    rng = random.Random(f"{s['seed']}-{s['run']}-{s['level']}")
    while True:
        walls = {(x, 0) for x in range(COLS)} | {(x, ROWS - 1) for x in range(COLS)}
        walls |= {(0, y) for y in range(ROWS)} | {(COLS - 1, y) for y in range(ROWS)}
        for _ in range(int((COLS - 2) * (ROWS - 2) * 0.17)):
            walls.add((rng.randint(2, COLS - 3), rng.randint(1, ROWS - 2)))
        hero = (1, rng.randint(1, ROWS - 2))
        ex = (COLS - 2, rng.randint(1, ROWS - 2))
        walls -= {hero, ex}
        reach = bfs(hero, walls)
        if ex not in reach:
            continue
        cand = [p for p in reach if p not in (hero, ex) and abs(p[0] - hero[0]) + abs(p[1] - hero[1]) > 3]
        rng.shuffle(cand)
        nb = min(2 + s["level"], 8)
        if len(cand) < nb + 4:
            continue
        armored = max(0, s["level"] - 2)
        s["bugs"] = [{"x": p[0], "y": p[1], "hp": 2 if i < armored else 1} for i, p in enumerate(cand[:nb])]
        s["coins"] = [list(p) for p in cand[nb:nb + 4]]
        s["walls"] = sorted(list(w) for w in walls if 0 < w[0] < COLS - 1 and 0 < w[1] < ROWS - 1)
        s["hero"], s["exit"] = list(hero), list(ex)
        return


def walls_of(s):
    w = {tuple(p) for p in s["walls"]}
    w |= {(x, 0) for x in range(COLS)} | {(x, ROWS - 1) for x in range(COLS)}
    w |= {(0, y) for y in range(ROWS)} | {(COLS - 1, y) for y in range(ROWS)}
    return w


def play(s, login, d):
    s["turn"] += 1
    me = s["players"].setdefault(login, {"moves": 0, "kills": 0, "coins": 0})
    me["moves"] += 1
    walls = walls_of(s)
    hx, hy = s["hero"]
    tx, ty = hx + DIRS[d][0], hy + DIRS[d][1]
    bug = next((b for b in s["bugs"] if (b["x"], b["y"]) == (tx, ty)), None)
    out = []

    if (tx, ty) in walls:
        out.append("bonked into a wall")
    elif bug:
        bug["hp"] -= 1
        if bug["hp"] <= 0:
            s["bugs"].remove(bug)
            s["score"] += 10
            me["kills"] += 1
            out.append("squashed a bug (+10)")
        else:
            out.append("cracked an armored bug's shell")
    else:
        s["hero"] = [tx, ty]
        if [tx, ty] in s["coins"]:
            s["coins"].remove([tx, ty])
            s["score"] += 5
            me["coins"] += 1
            out.append("grabbed a coin (+5)")
        if [tx, ty] == s["exit"]:
            s["level"] += 1
            s["score"] += 25
            s["hp"] = min(MAXHP, s["hp"] + 1)
            s["best_level"] = max(s.get("best_level", 1), s["level"])
            new_level(s)
            out.append(f"took the stairs to level {s['level']} (+25, +1 HP)")
            return log(s, login, d, out)
        if not out:
            out.append("moved " + d)

    # ---- bugs' turn
    rng = random.Random(f"{s['seed']}-{s['turn']}")
    hx, hy = s["hero"]
    taken = {(b["x"], b["y"]) for b in s["bugs"]}
    bites = 0
    for b in s["bugs"]:
        dist = abs(b["x"] - hx) + abs(b["y"] - hy)
        if dist == 1:
            if rng.random() < 0.55:
                bites += 1
            continue
        steps = list(DIRS.values())
        rng.shuffle(steps)
        if dist <= 6:
            steps.sort(key=lambda v: abs(b["x"] + v[0] - hx) + abs(b["y"] + v[1] - hy))
        elif rng.random() < 0.5:
            continue
        for vx, vy in steps:
            n = (b["x"] + vx, b["y"] + vy)
            if n in walls or n in taken or list(n) in (s["hero"], s["exit"]):
                continue
            if dist <= 6 and abs(n[0] - hx) + abs(n[1] - hy) >= dist:
                break
            taken.discard((b["x"], b["y"]))
            b["x"], b["y"] = n
            taken.add(n)
            break
    if bites:
        s["hp"] -= bites
        out.append(f"got bitten (-{bites} HP)")
    if s["hp"] <= 0:
        final, lvl = s["score"], s["level"]
        if final > s["hiscore"]:
            s["hiscore"], s["hiscore_by"] = final, login
            out.append(f"GAME OVER... but a NEW HI-SCORE: {final}!")
        else:
            out.append(f"GAME OVER on level {lvl} with {final} pts")
        s["graveyard"] = ([{"run": s["run"], "score": final, "level": lvl, "by": login}] + s.get("graveyard", []))[:5]
        s["run"] += 1
        s.update(level=1, hp=MAXHP, score=0)
        new_level(s)
    return log(s, login, d, out)


def log(s, login, d, out):
    text = ", ".join(out)
    s["log"] = ([{"login": login, "dir": d, "text": text, "turn": s["turn"]}] + s["log"])[:6]
    s["message"] = f"@{login} {text}"
    return text


# ------------------------------------------------------------------ drawing
def ptext(text, x, y, size=8, fill=PAPER, anchor="start"):
    k = size / 8
    w = len(text) * 8 * k
    x = x - (w if anchor == "end" else w / 2 if anchor == "middle" else 0)
    parts = []
    for i, ch in enumerate(text):
        d = GLYPHS[ch] if ch in GLYPHS else GLYPHS.get(ch.upper(), GLYPHS["?"])
        if d:
            parts.append(f'<path transform="translate({x + i * 8 * k:.1f} {y}) scale({k})" d="{d}"/>')
    return f'<g fill="{fill}">{"".join(parts)}</g>'


def sprite(rows, pal, x, y, px, cls=""):
    r = []
    for j, row in enumerate(rows):
        for i, c in enumerate(row):
            if c != ".":
                r.append(f'<rect x="{x + i * px:.1f}" y="{y + j * px:.1f}" width="{px + .2:.1f}" height="{px + .2:.1f}" fill="{pal[c]}"/>')
    c = f' class="{cls}"' if cls else ""
    return f"<g{c}>{''.join(r)}</g>"


HERO = ["...HHHHHH...", "..HHHHHHHH.P", "..HSSSSSSH.P", "..SKSSSSKS.P", "..SSSSSSSS.P",
        "...SSMMSS..P", ".RRRRRRRRRYY", "RRRRRRRRRRS.", "S.RRRRRRR...", "..RRRRRRR...", "..DD...DD...", "..KK...KK..."]
HERO_PAL = {"H": "#2a211c", "S": "#e0ad84", "K": INK, "M": "#a8433a", "R": RED, "P": PAPER, "Y": YELLOW, "D": "#3b3a52"}
BUG_A = ["..A......A..", "...A....A...", "....GGGG....", "...GGGGGG...", "L.GEEGGEEG.L", ".LGGGGGGGGL.",
         "..GGDGGDGG..", "L.GGGGGGGG.L", ".LGGDGGDGGL.", "..GGGGGGGG..", "...GGGGGG...", "..L......L.."]
BUG_B = [r.replace("L", ".") for r in BUG_A]
for i, j in ((4, 0), (4, 11), (7, 0), (7, 11)):
    BUG_B[i] = BUG_B[i][:j] + "." + BUG_B[i][j + 1:]
BUG_B[5], BUG_B[8] = "LGGGGGGGGGGL", "LGGDGGDGGGGL"
COIN = ["..YYYY..", ".YyyyyY.", "YyYYYYyY", "YyYOOYyY", "YyYOOYyY", "YyYYYYyY", ".YyyyyY.", "..YYYY.."]
COIN_PAL = {"Y": YELLOW, "y": "#fff1a8", "O": "#d9a520"}
STAIRS = ["BBBBBBBBBB", "B........B", "B......SSB", "B......SSB", "B....SSSSB", "B....SSSSB", "B..SSSSSSB", "B..SSSSSSB", "BSSSSSSSSB", "BBBBBBBBBB"]
HEART = [".RR.RR.", "RRRRRRR", "RRRRRRR", ".RRRRR.", "..RRR..", "...R..."]


def render(s):
    W, TOP = 840, 72
    bx = (W - COLS * TILE) // 2
    H = TOP + ROWS * TILE + 56
    walls = walls_of(s)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
         f'aria-label="BUG SLAYER board — level {s["level"]}, {s["hp"]} HP, score {s["score"]}">',
         "<style>.fa{animation:fa .5s steps(1) infinite}.fb{animation:fb .5s steps(1) infinite}"
         "@keyframes fa{50%{opacity:0}}@keyframes fb{0%{opacity:0}50%{opacity:1}}"
         ".coin{transform-box:fill-box;transform-origin:center;animation:spin 1.2s ease-in-out infinite}"
         "@keyframes spin{50%{transform:scaleX(.15)}}"
         ".hero{animation:bob 1s steps(2) infinite}@keyframes bob{50%{transform:translateY(-3px)}}"
         ".glow{animation:glow 1.4s ease-in-out infinite}@keyframes glow{50%{opacity:.25}}"
         ".blink{animation:bl 1s steps(1) infinite}@keyframes bl{50%{opacity:0}}</style>",
         '<defs><pattern id="d" width="8" height="8" patternUnits="userSpaceOnUse"><circle cx="4" cy="4" r="1.2" fill="#f1eadb" opacity=".05"/></pattern>'
         '<pattern id="sc" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="1" fill="#000" opacity=".22"/></pattern></defs>',
         f'<rect width="{W}" height="{H}" fill="{INK}"/>']
    # HUD
    o.append(ptext("LV", 24, 32, 10, RED) + ptext(f"{s['level']:02d}", 24, 58, 20, PAPER))
    o.append(ptext("HP", 112, 32, 10, RED))
    for i in range(MAXHP):
        o.append(sprite(HEART, {"R": RED if i < s["hp"] else LINE}, 112 + i * 34, 38, 4))
    o.append(ptext("SCORE", 320, 32, 10, RED) + ptext(f"{s['score']:05d}", 320, 58, 20, PAPER))
    o.append(ptext("HI-SCORE", 500, 32, 10, YELLOW) + ptext(f"{s['hiscore']:05d}", 500, 58, 20, YELLOW))
    o.append(ptext(f"RUN {s['run']}", W - 24, 34, 10, MUTED, "end") + ptext(f"TURN {s['turn']}", W - 24, 56, 10, MUTED, "end"))
    # board
    o.append(f'<rect x="{bx - 6}" y="{TOP - 6}" width="{COLS * TILE + 12}" height="{ROWS * TILE + 12}" fill="{RED}"/>')
    o.append(f'<rect x="{bx}" y="{TOP}" width="{COLS * TILE}" height="{ROWS * TILE}" fill="{INK2}"/>')
    o.append(f'<rect x="{bx}" y="{TOP}" width="{COLS * TILE}" height="{ROWS * TILE}" fill="url(#d)"/>')
    for (x, y) in sorted(walls):
        X, Y = bx + x * TILE, TOP + y * TILE
        o.append(f'<rect x="{X}" y="{Y}" width="{TILE}" height="{TILE}" fill="#2a2621"/>'
                 f'<rect x="{X}" y="{Y}" width="{TILE}" height="4" fill="#3a352e"/>'
                 f'<path d="M{X} {Y + 19}h{TILE}M{X} {Y + 37}h{TILE}M{X + 28} {Y + 4}v15M{X + 14} {Y + 19}v18M{X + 42} {Y + 19}v18M{X + 28} {Y + 37}v19" stroke="{INK}" stroke-width="2"/>')
    ex, ey = s["exit"]
    o.append(f'<g class="glow"><rect x="{bx + ex * TILE + 2}" y="{TOP + ey * TILE + 2}" width="{TILE - 4}" height="{TILE - 4}" fill="{BLUE}" opacity=".35"/></g>')
    o.append(sprite(STAIRS, {"B": BLUE, "S": PAPER}, bx + ex * TILE + 8, TOP + ey * TILE + 8, 4))
    for cx, cy in s["coins"]:
        o.append(sprite(COIN, COIN_PAL, bx + cx * TILE + 12, TOP + cy * TILE + 12, 4, "coin"))
    for b in s["bugs"]:
        pal = {"A": MUTED, "L": MUTED, "G": GREEN if b["hp"] == 1 else PEACH, "E": RED if b["hp"] == 1 else INK, "D": "#156b47" if b["hp"] == 1 else "#b5603c"}
        X, Y = bx + b["x"] * TILE + 4, TOP + b["y"] * TILE + 4
        o.append(sprite(BUG_A, pal, X, Y, 4, "fa") + sprite(BUG_B, pal, X, Y, 4, "fb"))
    hx, hy = s["hero"]
    o.append(sprite(HERO, HERO_PAL, bx + hx * TILE + 4, TOP + hy * TILE + 4, 4, "hero"))
    o.append(f'<rect x="{bx}" y="{TOP}" width="{COLS * TILE}" height="{ROWS * TILE}" fill="url(#sc)"/>')
    # message bar
    msg = (s.get("message") or "A NEW RUN BEGINS. PICK A DIRECTION BELOW!").upper()
    msg = msg if len(msg) <= 84 else msg[:81] + "..."
    o.append(f'<rect x="0" y="{H - 40}" width="{W}" height="40" fill="{INK2}"/><rect x="0" y="{H - 40}" width="{W}" height="2" fill="{LINE}"/>')
    o.append(f'<g class="blink">{ptext(">", 20, H - 15, 8, RED)}</g>' + ptext(msg, 36, H - 15, 8, PAPER2))
    o.append(f'<rect x="1.5" y="1.5" width="{W - 3}" height="{H - 3}" fill="none" stroke="{PAPER}" stroke-width="3"/></svg>')
    return "".join(o)


def readme_block(s):
    L = [f'<p align="center"><img src="assets/game/board.svg?turn={s["turn"]}" width="100%" alt="BUG SLAYER — level {s["level"]}, {s["hp"]}/{MAXHP} HP, score {s["score"]}" /></p>', ""]
    if s["log"]:
        L += ["<table align=\"center\"><tr><th>🕹️ LAST MOVES</th><th>🏆 HALL OF FAME</th></tr><tr><td valign=\"top\">", ""]
        for e in s["log"][:5]:
            L.append(f'{ARROW[e["dir"]]} <a href="https://github.com/{e["login"]}">@{e["login"]}</a> <sub>{e["text"]}</sub><br/>')
        L += ["", '</td><td valign="top">', ""]
        top = sorted(s["players"].items(), key=lambda kv: (-(kv[1]["kills"] * 10 + kv[1]["coins"] * 5 + kv[1]["moves"]), kv[0]))[:5]
        for i, (login, p) in enumerate(top):
            medal = ["🥇", "🥈", "🥉", "4.", "5."][i]
            L.append(f'{medal} <a href="https://github.com/{login}">@{login}</a> <sub>{p["kills"]} 🐛 · {p["coins"]} 🪙 · {p["moves"]} moves</sub><br/>')
        if s.get("hiscore_by"):
            L.append(f'<br/><sub>👑 HI-SCORE <b>{s["hiscore"]}</b> — set by @{s["hiscore_by"]}</sub>')
        L += ["", "</td></tr></table>"]
    else:
        L.append('<p align="center"><sub>no moves yet — be player one 👾</sub></p>')
    return "\n".join(L)


def write_outputs(s):
    os.makedirs(os.path.dirname(BOARD), exist_ok=True)
    open(BOARD, "w").write(render(s))
    txt = open(README).read()
    txt = re.sub(r"<!--GAME:START-->.*<!--GAME:END-->", lambda m: "<!--GAME:START-->\n" + readme_block(s) + "\n<!--GAME:END-->", txt, flags=re.S)
    open(README, "w").write(txt)
    json.dump(s, open(STATE, "w"), indent=1)


# ------------------------------------------------------------------ github glue
def gh(*args, inp=None):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, input=inp).stdout


def run_moves():
    s = json.load(open(STATE))
    issues = json.loads(gh("api", f"repos/{REPO}/issues?state=open&per_page=100"))
    issues = sorted((i for i in issues if "pull_request" not in i and i["title"].lower().startswith("bugslayer|")), key=lambda i: i["number"])
    done = []
    for i in issues:
        d = i["title"].split("|", 1)[1].strip().lower()
        login = i["user"]["login"]
        if d not in DIRS:
            done.append({"n": i["number"], "body": f"🤔 `{d}` isn't a move. Try up, down, left or right from [the game](https://github.com/{OWNER})."})
            continue
        lvl0 = s["level"]
        text = play(s, login, d)
        hp = "❤️" * max(s["hp"], 0) + "🖤" * (MAXHP - max(s["hp"], 0))
        body = (f"{ARROW[d]} **@{login}** {text}.\n\n"
                f"`LV {s['level']:02d}` {hp} `SCORE {s['score']:05d}` `HI {s['hiscore']:05d}`\n\n"
                f"Thanks for playing! **[→ Back to the board](https://github.com/{OWNER})** (give it a refresh).")
        done.append({"n": i["number"], "body": body})
    if not done:
        print("no moves")
    write_outputs(s)
    json.dump(done, open(PENDING, "w"))
    print(f"played {len(done)} move(s)")


def close_moves():
    if not os.path.exists(PENDING):
        return
    for d in json.load(open(PENDING)):
        gh("api", f"repos/{REPO}/issues/{d['n']}/comments", "-f", f"body={d['body']}")
        gh("api", "-X", "PATCH", f"repos/{REPO}/issues/{d['n']}", "-f", "state=closed", "-f", "state_reason=completed")
    os.remove(PENDING)


def fresh(seed="bugslayer"):
    s = {"seed": seed, "run": 1, "level": 1, "hp": MAXHP, "score": 0, "hiscore": 0, "turn": 0,
         "players": {}, "log": [], "message": "", "best_level": 1}
    new_level(s)
    return s


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "play"
    if cmd == "play":
        run_moves()
    elif cmd == "close":
        close_moves()
    elif cmd == "reset":
        write_outputs(fresh())
    elif cmd == "render":
        write_outputs(json.load(open(STATE)))
