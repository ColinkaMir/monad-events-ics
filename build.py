#!/usr/bin/env python3
"""Build a subscribable ICS calendar of Monad network events.

Sources:
  1. gmonads.com/api/events: the network events calendar gmonads shows at /events (load tests,
     and as they are scheduled: releases, deprecations, activation epochs). All credit to gmonads.
  2. Monad Foundation node-operator announcements that verify: github.com/monad-crypto/mf-nodeops-comms,
     each with good signatures from 2+ keys listed at docs.monad.xyz/node-ops/gpg-keys.json. They go
     in as all-day entries on their publication date, linking to the text. Dates inside the text are
     NOT parsed: that is too easy to get wrong.

gmonads only serves upcoming events, so past ones are kept from a local store for HISTORY_DAYS,
otherwise every finished event would vanish from subscribers' calendars. An upcoming event that
disappears from gmonads is treated as cancelled and dropped.

  python3 build.py                 # build into OUT_DIR
  OUT_DIR=/tmp/x python3 build.py  # anywhere else
"""
import datetime as dt
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request

GMONADS = "https://www.gmonads.com/api/events"
SITE = "https://prooflines.org/monad/events/"
FEED = SITE + "monad.ics"
HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.getenv("STORE", os.path.join(HERE, "data", "events.json"))
OUT_DIR = os.getenv("OUT_DIR", os.path.join(HERE, "out"))
COMMS = os.getenv("COMMS_WATCH", "/home/solana/monad-comms-watch.py")
HISTORY_DAYS = 120
ALARM_TYPES = {"load-test", "release", "upgrade", "activation", "deprecation"}
NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(s):
    s = re.sub(r"\s*(UTC|Z)$", "+00:00", s.strip())   # announcements write both ...Z and ...UTC
    return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc)


def fetch_gmonads():
    req = urllib.request.Request(GMONADS, headers={"User-Agent": "prooflines-monad-events-ics/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    out = {}
    for e in d.get("events", []):
        if not e.get("id") or not e.get("start"):
            continue
        out["gm:" + e["id"]] = {
            "source": "gmonads",
            "title": e.get("title") or "Monad network event",
            "type": e.get("type") or "event",
            "start": e["start"], "end": e.get("end") or e["start"],
            "allDay": bool(e.get("allDay")),
            "url": e.get("url") or "https://www.gmonads.com/events",
            "description": e.get("description") or "",
        }
    return out


def subject_of(text):
    """First line after the header, without emoji, :shortcodes: and the CODE colour prefix."""
    code = ""
    for raw in text.splitlines():
        l = raw.strip()
        if not l or re.match(r"(MF )?Announcement #\d+|Created:", l):
            continue
        l = re.sub(r":[a-z0-9_+-]+:", " ", l)
        l = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", " ", l)
        m = re.match(r"(?i)\s*code (green|orange|red|yellow)\b\s*:?\s*(.*)", l)
        if m:
            code = "Code " + m.group(1).capitalize()
            l = m.group(2)
        l = re.sub(r"\s+", " ", l).strip(" :*.")
        if l:
            return l[:80], code
    return "announcement", code


def verified_announcements():
    """Reuse the comms watcher's clone and GPG check; the watcher keeps the clone fresh."""
    spec = importlib.util.spec_from_file_location("comms", COMMS)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    ann_dir = os.path.join(m.CLONE, "announcements")
    if not os.path.isdir(ann_dir):
        return {}
    keys = m.authorised_keys()
    active = {k["fingerprint"]: n for n, k in keys.items() if k["status"] == "active"}
    home, _, _ = m.make_keyring(active)
    out = {}
    try:
        for n in sorted(os.listdir(ann_dir)):
            d = os.path.join(ann_dir, n)
            txt = os.path.join(d, "announcement.txt")
            if not os.path.isfile(txt):
                continue
            v = m.verify(home, d, active)
            if not v["ok"]:
                continue
            text = open(txt, errors="replace").read()
            c = re.search(r"Created:\s*(\S+)", text)
            if not c:
                continue
            subject, code = subject_of(text)
            num = re.search(r"Announcement #(\d+)", text)
            day = iso(c.group(1)).date().isoformat()
            out["mf:" + n] = {
                "source": "mf",
                "title": f"MF #{num.group(1) if num else n}: {subject[:80]}" + (f" ({code})" if code else ""),
                "type": "announcement",
                "start": day, "end": day, "allDay": True,
                "url": m.WEB + n,
                "description": (f"Monad Foundation node-operator announcement, signatures verified "
                                f"({', '.join(v['signers'])}).\n\n{text.strip()[:1500]}"),
            }
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return out


def merge(store, gm, mf):
    """Store keeps first-seen stamps (stable DTSTAMP) and past events."""
    events = store.get("events", {})
    for key, e in list(gm.items()) + list(mf.items()):
        old = events.get(key, {})
        e["firstSeen"] = old.get("firstSeen") or NOW.isoformat()
        e["changed"] = old.get("changed") or e["firstSeen"]
        if {k: old.get(k) for k in ("title", "start", "end", "description")} != \
                {k: e.get(k) for k in ("title", "start", "end", "description")} and old:
            e["changed"] = NOW.isoformat()
        events[key] = e
    keep = {}
    horizon = NOW - dt.timedelta(days=HISTORY_DAYS)
    for key, e in events.items():
        start = iso(e["start"] + ("T00:00:00Z" if e["allDay"] else ""))
        if start < horizon:
            continue
        if e["source"] == "gmonads" and key not in gm and start > NOW:
            continue                     # upcoming but gone from gmonads: cancelled
        keep[key] = e
    return keep


def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    """RFC 5545: lines of at most 75 octets, continuation lines start with a space."""
    b = line.encode()
    out, cur = [], b""
    for ch in line:
        c = ch.encode()
        if len(cur) + len(c) > (75 if not out else 74):
            out.append(cur)
            cur = b""
        cur += c
    out.append(cur)
    return "\r\n ".join(x.decode() for x in out)


def stamp(s):
    return iso(s).strftime("%Y%m%dT%H%M%SZ")


def ics(events):
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ProofLines//Monad network events//EN",
         "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Monad network events",
         "X-WR-CALDESC:Load tests\\, releases and Foundation announcements for Monad node operators."
         " Events from gmonads.com/events\\, announcements verified against the Foundation GPG keys.",
         "X-WR-TIMEZONE:UTC", "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]
    for key, e in sorted(events.items(), key=lambda kv: kv[1]["start"]):
        uid = hashlib.sha1(key.encode()).hexdigest()[:24] + "@prooflines.org"
        L += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp(e['changed'])}"]
        if e["allDay"]:
            d0 = dt.date.fromisoformat(e["start"][:10])
            d1 = max(dt.date.fromisoformat(e["end"][:10]), d0 + dt.timedelta(days=1))
            L += [f"DTSTART;VALUE=DATE:{d0:%Y%m%d}", f"DTEND;VALUE=DATE:{d1:%Y%m%d}", "TRANSP:TRANSPARENT"]
        else:
            L += [f"DTSTART:{stamp(e['start'])}", f"DTEND:{stamp(e['end'])}"]
        src = ("Source: gmonads.com/events (Monad network events calendar)" if e["source"] == "gmonads"
               else "Source: github.com/monad-crypto/mf-nodeops-comms")
        desc = (e["description"] + "\n\n" if e["description"] else "") + src + f"\nCalendar: {SITE}"
        L += [f"SUMMARY:{esc(e['title'])}", f"DESCRIPTION:{esc(desc)}", f"URL:{e['url']}",
              f"CATEGORIES:{esc(e['type'])}"]
        if not e["allDay"] and e["type"] in ALARM_TYPES:
            L += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(e['title'])}",
                  "TRIGGER:-PT1H", "END:VALARM"]
        L.append("END:VEVENT")
    L.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in L) + "\r\n"


def page(events, gm_ok):
    e_ = html.escape
    up = sorted((e for e in events.values()
                 if iso(e["start"] + ("T23:59:59Z" if e["allDay"] else "")) >= NOW),
                key=lambda e: e["start"])
    rows = []
    for e in up[:20]:
        when = (e["start"][:10] + " (all day)") if e["allDay"] else iso(e["start"]).strftime("%Y-%m-%d %H:%M UTC")
        rows.append(f"<tr><td class=m>{e_(when)}</td><td><a href=\"{e_(e['url'])}\">{e_(e['title'])}</a></td></tr>")
    recent = sorted((e for e in events.values() if e["source"] == "mf"), key=lambda e: e["start"], reverse=True)[:5]
    rec = "".join(f"<tr><td class=m>{e_(e['start'][:10])}</td><td><a href=\"{e_(e['url'])}\">{e_(e['title'])}</a></td></tr>"
                  for e in recent)
    tpl = open(os.path.join(HERE, "page.html")).read()
    return (tpl.replace("{{FEED}}", FEED).replace("{{WEBCAL}}", FEED.replace("https://", "webcal://"))
               .replace("{{GCAL}}", "https://calendar.google.com/calendar/r?cid=" + urllib.parse.quote(FEED, safe=""))
               .replace("{{ROWS}}", "\n".join(rows) or "<tr><td colspan=2>No upcoming events listed right now.</td></tr>")
               .replace("{{RECENT}}", rec or "<tr><td colspan=2>None yet.</td></tr>")
               .replace("{{UPDATED}}", NOW.strftime("%Y-%m-%d %H:%M UTC"))
               .replace("{{STALE}}", "" if gm_ok else
                        "<p class=warn>gmonads could not be reached on the last refresh; showing the last known events.</p>"))


def main():
    try:
        store = json.load(open(STORE))
    except Exception:
        store = {}
    gm_ok = True
    try:
        gm = fetch_gmonads()
    except Exception as ex:
        print(f"gmonads fetch failed: {ex}", file=sys.stderr)
        gm_ok, gm = False, {k: v for k, v in store.get("events", {}).items() if v["source"] == "gmonads"}
    try:
        mf = verified_announcements()
    except Exception as ex:
        print(f"announcements skipped: {ex}", file=sys.stderr)
        mf = {k: v for k, v in store.get("events", {}).items() if v["source"] == "mf"}
    events = merge(store, gm, mf)
    store = {"events": events, "lastBuild": NOW.isoformat(),
             "lastGmonadsOk": NOW.isoformat() if gm_ok else store.get("lastGmonadsOk")}
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    json.dump(store, open(STORE + ".tmp", "w"), indent=1)
    os.replace(STORE + ".tmp", STORE)
    os.makedirs(OUT_DIR, exist_ok=True)
    open(os.path.join(OUT_DIR, "monad.ics"), "w", newline="").write(ics(events))
    open(os.path.join(OUT_DIR, "index.html"), "w").write(page(events, gm_ok))
    print(f"{len(events)} events ({sum(1 for e in events.values() if e['source']=='gmonads')} gmonads, "
          f"{sum(1 for e in events.values() if e['source']=='mf')} announcements), gmonads ok={gm_ok}")
    return 0 if gm_ok else 1


if __name__ == "__main__":
    sys.exit(main())
