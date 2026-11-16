# AggieWatch

Get notified when the TAMU class sections you want open up. It works like AggieSeek but runs on your own computer, and it only needs Python 3 (no installs).

## Setup (2 minutes)

1. Install the **ntfy** app on your phone (iOS/Android, free) and subscribe to a topic name nobody else would guess, e.g. `adam-seats-8f3k2`.
2. Put the classes you want in `watchlist.txt`:
   ```
   10722          # a specific CRN
   ECEN 214       # any section of ECEN 214
   ECEN 214 501   # one specific section
   ```
3. Test notifications:
   ```
   python3 aggiewatch.py --ntfy adam-seats-8f3k2 --test-notify
   ```
4. Run it:
   ```
   python3 aggiewatch.py --ntfy adam-seats-8f3k2 --desktop
   ```

## Handy commands

| Command | What it does |
|---|---|
| `--status` | Show open/closed status for your watchlist once, then exit |
| `--list-terms` | List term codes (default term is the newest College Station one) |
| `--term 202711` | Pick a term explicitly (202711 = Spring 2027 College Station) |
| `--interval 60` | Seconds between checks (default 90, min 30) |
| `--discord URL` | Also send alerts to a Discord webhook |
| `-w "MATH 308"` | Add a watch from the command line |

## How it works

It polls Howdy's public class search API (`howdyportal.tamu.edu/api/course-sections`) and watches each section's open/closed flag (`STUSEAT_OPEN`). The public API no longer shows exact seat counts, so alerts say "open," not "3 seats left." You get one alert when a section goes from closed to open, plus one at startup for anything that's already open.

## Keeping it running

It only checks while your computer is on and the script is running. To keep it going after you close the terminal:
- macOS/Linux: `nohup python3 aggiewatch.py --ntfy TOPIC > aggiewatch.log 2>&1 &`
- Or run it on a free always-on box (Oracle Cloud free tier, a Raspberry Pi, etc.).

Please keep the interval at 60s or higher. Each check downloads the whole term's section list, and hammering Howdy won't get you a seat any faster.
