# monad-events-ics

A subscribable calendar of Monad network events for node operators: testnet load tests, releases and
Monad Foundation node-operator announcements, in Google, Apple or Outlook calendar.

**Subscribe:** `https://prooflines.org/monad/events/monad.ics` · page with one-click buttons:
https://prooflines.org/monad/events/

## Where the events come from

- **[gmonads.com/events](https://www.gmonads.com/events)**, the network events calendar gmonads keeps:
  load tests now, releases, deprecations and activation epochs as they are scheduled. Read from
  `gmonads.com/api/events`. All credit to gmonads; this only makes their calendar subscribable, and
  should step aside once gmonads publishes its own feed.
- **Foundation announcements** from
  [monad-crypto/mf-nodeops-comms](https://github.com/monad-crypto/mf-nodeops-comms), included only
  when `announcement.sig` carries good signatures from at least two distinct keys whose primary
  fingerprints are listed as active at
  [docs.monad.xyz/node-ops/gpg-keys.json](https://docs.monad.xyz/node-ops/gpg-keys.json). They appear
  as all-day entries on the date they were created, linking to the text. Dates inside the text are
  not parsed.

## Behaviour

- Stable UIDs, so a moved event moves in your calendar instead of being duplicated.
- Times in UTC; a one-hour reminder on load tests and releases.
- gmonads lists only upcoming events, so past ones are kept locally for 120 days. An upcoming event
  that disappears from gmonads is treated as cancelled.
- If gmonads cannot be reached, the last known events stay published and the page says so.
- Google refreshes subscribed calendars on its own schedule (often hours). Apple and Outlook
  refresh more often.

## Run it

```bash
python3 build.py              # writes out/monad.ics and out/index.html, keeps data/events.json
OUT_DIR=/some/dir python3 build.py
```

Python 3 standard library and `gpg`. The announcement check reuses a GPG verifier that expects a
clone of mf-nodeops-comms; point `COMMS_WATCH` at your own, or the announcements are skipped and
only gmonads events are published.

GPL-3.0.
