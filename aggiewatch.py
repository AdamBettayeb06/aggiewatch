#!/usr/bin/env python3
"""
AggieWatch - get notified when Texas A&M class sections open up.

Polls the public Howdy class search (the same data AggieSeek uses) and sends
a push notification when a section you're watching flips from closed to open.

Watchlist entries (one per line in watchlist.txt, or via --watch):
    10722            -> a specific CRN
    ECEN 214         -> ANY section of ECEN 214
    ECEN 214 501     -> a specific section number of ECEN 214

Notifications (use any combination):
    --ntfy TOPIC        push to your phone via the free ntfy app (https://ntfy.sh)
    --discord URL       Discord webhook
    --desktop           local desktop notification (macOS / Linux / Windows)

Only uses the Python standard library - no pip install needed.
"""

import argparse
import json
import os
import platform
import random
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

BASE = "https://howdyportal.tamu.edu"
TERMS_URL = BASE + "/api/all-terms"
SECTIONS_URL = BASE + "/api/course-sections"
CLASS_SEARCH_PAGE = BASE + "/uPortal/p/public-class-search-ui.ctf1/max/render.uP"
UA = "AggieWatch/1.0 (personal seat notifier)"


# ---------------------------------------------------------------- HTTP helpers
def http_json(url, payload=None, timeout=60):
    data = None
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get_terms():
    return http_json(TERMS_URL)


def pick_default_term(terms):
    """Newest 'College Station' term (Howdy lists newest first)."""
    for t in terms:
        if t.get("STVTERM_DESC", "").endswith("College Station"):
            return t["STVTERM_CODE"], t["STVTERM_DESC"]
    t = terms[0]
    return t["STVTERM_CODE"], t["STVTERM_DESC"]


def get_sections(term):
    rows = http_json(SECTIONS_URL, {"startRow": 0, "endRow": 0,
                                     "termCode": term, "publicSearch": "Y"})
    return rows


# ---------------------------------------------------------------- watchlist
def parse_watch(entry):
    parts = entry.upper().replace("-", " ").split()
    if not parts:
        return None
    online = False
    if parts[-1] == "ONLINE":
        online = True
        parts = parts[:-1]
    w = _parse_parts(parts, entry)
    if online:
        w["online"] = True
        w["label"] += " (online only)"
    return w


def _parse_parts(parts, entry):
    if len(parts) == 1 and parts[0].isdigit():
        return {"crn": parts[0], "label": f"CRN {parts[0]}"}
    if len(parts) in (2, 3):
        w = {"subject": parts[0], "course": parts[1]}
        if len(parts) == 3:
            w["section"] = parts[2]
        w["label"] = " ".join(parts)
        return w
    raise ValueError(f"Can't understand watch entry: {entry!r}")


def load_watchlist(path, extra):
    entries = list(extra or [])
    if path and os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    entries.append(line)
    return [w for w in (parse_watch(e) for e in entries) if w]


def is_online(s):
    mode = (s.get("SWV_CLASS_SEARCH_INST_TYPE") or "").lower()
    return "web based" in mode or "online" in mode


def matches(w, s):
    if w.get("online") and not is_online(s):
        return False
    if "crn" in w:
        return s["SWV_CLASS_SEARCH_CRN"] == w["crn"]
    if s["SWV_CLASS_SEARCH_SUBJECT"] != w["subject"]:
        return False
    if s["SWV_CLASS_SEARCH_COURSE"] != w["course"]:
        return False
    return "section" not in w or s["SWV_CLASS_SEARCH_SECTION"] == w["section"]


def describe(s):
    meets = []
    try:
        for m in json.loads(s.get("SWV_CLASS_SEARCH_JSON_CLOB") or "[]"):
            days = "".join(m.get(k) or "" for k in (
                "SSRMEET_MON_DAY", "SSRMEET_TUE_DAY", "SSRMEET_WED_DAY",
                "SSRMEET_THU_DAY", "SSRMEET_FRI_DAY", "SSRMEET_SAT_DAY",
                "SSRMEET_SUN_DAY"))
            if days and m.get("SSRMEET_BEGIN_TIME"):
                meets.append(f"{m.get('SSRMEET_MTYP_CODE','')} {days} "
                             f"{m['SSRMEET_BEGIN_TIME']}-{m['SSRMEET_END_TIME']}")
    except (ValueError, TypeError):
        pass
    try:
        prof = ", ".join(p["NAME"] for p in json.loads(
            s.get("SWV_CLASS_SEARCH_INSTRCTR_JSON") or "[]"))
    except (ValueError, TypeError, KeyError):
        prof = ""
    head = (f"{s['SWV_CLASS_SEARCH_SUBJECT']} {s['SWV_CLASS_SEARCH_COURSE']}-"
            f"{s['SWV_CLASS_SEARCH_SECTION']} (CRN {s['SWV_CLASS_SEARCH_CRN']}) "
            f"{s.get('SWV_CLASS_SEARCH_TITLE','')}")
    extra = "; ".join(x for x in [prof, " | ".join(meets)] if x)
    return head + (f"\n{extra}" if extra else "")


def is_open(s):
    return s.get("STUSEAT_OPEN") == "Y"


# ---------------------------------------------------------------- notifiers
def notify(args, title, body):
    print(f"\n🔔 {title}\n{body}\n", flush=True)
    if args.ntfy:
        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{args.ntfy}", data=body.encode(),
                headers={"Title": title.encode("ascii", "ignore").decode(),
                         "Priority": "urgent", "Tags": "rotating_light",
                         "Click": CLASS_SEARCH_PAGE})
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:
            print(f"  [ntfy failed: {e}]")
    if args.discord:
        try:
            req = urllib.request.Request(
                args.discord,
                data=json.dumps({"content": f"**{title}**\n{body}"}).encode(),
                headers={"Content-Type": "application/json", "User-Agent": UA})
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:
            print(f"  [discord failed: {e}]")
    if args.desktop:
        desktop_notify(title, body)


def desktop_notify(title, body):
    sysname = platform.system()
    try:
        if sysname == "Darwin":
            esc = lambda x: x.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e",
                            f'display notification "{esc(body)}" with title '
                            f'"{esc(title)}" sound name "Glass"'], check=False)
        elif sysname == "Linux":
            subprocess.run(["notify-send", "-u", "critical", title, body], check=False)
        elif sysname == "Windows":
            ps = ("[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,"
                  "ContentType=WindowsRuntime]>$null;"
                  "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1);"
                  f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode('{title} - "
                  f"{body.splitlines()[0]}'.Replace(\"'\",\"\")))>$null;"
                  "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier"
                  "('AggieWatch').Show([Windows.UI.Notifications.ToastNotification]::new($t))")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)
    except Exception as e:
        print(f"  [desktop notify failed: {e}]")


# ---------------------------------------------------------------- main loop
def check_once(args, term, watches, state):
    sections = get_sections(term)
    found_any = set()
    for w in watches:
        hits = [s for s in sections if matches(w, s)]
        if not hits:
            if w["label"] not in state["missing_warned"]:
                print(f"⚠️  No sections found for {w['label']} in term {term}")
                state["missing_warned"].add(w["label"])
            continue
        for s in hits:
            crn = s["SWV_CLASS_SEARCH_CRN"]
            found_any.add(crn)
            now_open = is_open(s)
            was_open = state["open"].get(crn)
            if now_open and was_open is not True:
                reason = "is OPEN" if was_open is None else "just OPENED"
                notify(args, f"Seat open: {s['SWV_CLASS_SEARCH_SUBJECT']} "
                             f"{s['SWV_CLASS_SEARCH_COURSE']}-{s['SWV_CLASS_SEARCH_SECTION']}",
                       f"{describe(s)}\n{reason} - register in Howdy now!")
            elif was_open is True and not now_open:
                print(f"[{ts()}] closed again: {describe(s).splitlines()[0]}")
            state["open"][crn] = now_open
    return sections, found_any


def ts():
    return datetime.now().strftime("%H:%M:%S")


def main():
    ap = argparse.ArgumentParser(description="Notify when TAMU class sections open.")
    ap.add_argument("--watch", "-w", action="append",
                    help='CRN, "SUBJ NUM", or "SUBJ NUM SEC" (repeatable)')
    ap.add_argument("--file", "-f", default="watchlist.txt", help="watchlist file")
    ap.add_argument("--term", "-t", help="term code, e.g. 202711 (default: newest College Station term)")
    ap.add_argument("--interval", "-i", type=int, default=90,
                    help="seconds between checks (default 90; please don't go below 30)")
    ap.add_argument("--ntfy", help="ntfy.sh topic name for phone push notifications")
    ap.add_argument("--discord", help="Discord webhook URL")
    ap.add_argument("--desktop", action="store_true", help="show desktop notifications")
    ap.add_argument("--list-terms", action="store_true", help="print term codes and exit")
    ap.add_argument("--status", action="store_true", help="print current status once and exit")
    ap.add_argument("--test-notify", action="store_true", help="send a test notification and exit")
    args = ap.parse_args()

    if args.test_notify:
        notify(args, "AggieWatch test", "If you see this, notifications work. Gig 'em!")
        return

    if args.list_terms:
        for t in get_terms():
            print(f"{t['STVTERM_CODE']}  {t['STVTERM_DESC']}")
        return

    if args.term:
        term, term_desc = args.term, args.term
    else:
        term, term_desc = pick_default_term(get_terms())

    watches = load_watchlist(args.file, args.watch)
    if not watches:
        sys.exit("Nothing to watch. Add lines to watchlist.txt or use --watch \"ECEN 214\".")

    interval = max(30, args.interval)
    print(f"AggieWatch: {term_desc} ({term}) | watching: "
          f"{', '.join(w['label'] for w in watches)} | every {interval}s")
    if not (args.ntfy or args.discord or args.desktop):
        print("(No notifier set - alerts will only print here. Try --ntfy or --desktop.)")

    state = {"open": {}, "missing_warned": set()}

    if args.status:
        sections, _ = check_once(argparse.Namespace(ntfy=None, discord=None, desktop=False),
                                 term, watches, state)
        for w in watches:
            for s in (s for s in sections if matches(w, s)):
                mark = "OPEN  " if is_open(s) else "closed"
                print(f"  [{mark}] {describe(s).splitlines()[0]}")
        return

    failures = 0
    while True:
        try:
            _, found = check_once(args, term, watches, state)
            n_open = sum(1 for c in found if state["open"].get(c))
            print(f"[{ts()}] checked {len(found)} section(s), {n_open} open", flush=True)
            failures = 0
            sleep = interval
        except KeyboardInterrupt:
            raise
        except Exception as e:
            failures += 1
            sleep = min(600, interval * (2 ** min(failures, 4)))
            print(f"[{ts()}] error ({e}); retrying in {sleep}s", flush=True)
        time.sleep(sleep + random.uniform(0, 10))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
