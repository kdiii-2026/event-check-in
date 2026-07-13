# Event Check-In — Setup

## Running it (works right now, without Google Sheets)

```
cd /Users/kalebdavis/Claude/Artifacts/event-check-in/server
python3 server.py
```

Then open http://localhost:5050 on the laptop running it.

For other phones/tablets at the venue: make sure they're on the **same WiFi**
as the laptop, then open the address the terminal prints, e.g.:

```
Running on http://192.168.1.165:5050
```

(That IP will differ on your network — use whatever the terminal shows.)
Every device that opens that address shares the same live check-in list —
check someone in on one phone and it shows up on the others within ~2 seconds.

### Sharing it with other check-in stations

Right below the "Sheets sync" line, the terminal also prints a scannable
QR code pointing at the right address for *that* run — just have each
volunteer's phone camera scan it, no typing an IP required. Since the
address depends on whatever WiFi network the laptop is on that day, this
QR code is only good for the session it was printed in — if you stop and
restart the server (or it's a different day on different WiFi), scan the
new one.

The first time another device connects, macOS may pop up **"Do you want
the application 'Python' to accept incoming network connections?"** —
click **Allow**, or other devices won't be able to reach it at all.

If a device gets a blank page or "can't connect": double-check it's
actually on the same WiFi network as the laptop (not on cellular data,
and not on a "guest" WiFi network that isolates devices from each other —
some venues' guest WiFi blocks this kind of device-to-device traffic).

All check-in state is saved to `server/data/checkins.json` on the host
laptop, so if the server restarts mid-event nothing is lost.

To pull in new registrations that came in after you started (people keep
signing up right up to the event), just re-export the two CSVs from your
registration platform, overwrite the files at
`server/data/source/vbs.csv` and `server/data/source/youth-revival.csv`,
and refresh the page — the roster reloads automatically every 30 seconds.

## Connecting the Google Sheet (~5 minutes, one time)

This lets a Google Sheet update live as people get checked in, so anyone
with the link (not just people at the check-in table) can watch attendance
in real time.

Church/organization Google accounts commonly block "service account key"
creation as a security default (that's the "Service account key creation
is disabled" error). Rather than fight that policy, this uses a **Google
Apps Script Web App** instead — it runs as *you*, inside the Sheet itself,
so there's no Google Cloud console, no service account, and no key to
create at all.

1. **Create the Google Sheet**
   Make a new blank Google Sheet (e.g. "Antioch Event Check-In 2026").

2. **Open the script editor**
   In the Sheet: **Extensions → Apps Script**. It opens a separate
   code-editor tab, pre-loaded with an empty `Code.gs`.

3. **Paste in the script**
   Open [apps-script/Code.gs](apps-script/Code.gs) from this project,
   copy its full contents, and paste it over whatever is in the Apps
   Script editor (replacing the default empty function).

4. **Set the shared secret**
   Near the top of the pasted script there's a line:
   ```javascript
   var SECRET = "PASTE_YOUR_SECRET_HERE";
   ```
   Replace `PASTE_YOUR_SECRET_HERE` with the exact value currently in
   `server/config.json`'s `"webapp_secret"` field (already generated for
   you — just copy it over, don't make up a new one).

5. **Deploy it as a Web App**
   In the Apps Script editor: **Deploy → New deployment** → click the
   gear icon next to "Select type" → **Web app**.
   - Execute as: **Me**
   - Who has access: **Anyone**
     (this is what lets the check-in server reach it without a Google
     login prompt — the shared secret from step 4 is what keeps it from
     being usable by anyone else who might guess the URL)
   Click **Deploy**. The first time, Google will ask you to authorize the
   script — approve it (it's your own script acting on your own Sheet).

6. **Copy the Web App URL**
   After deploying you'll get a URL ending in `/exec`, like:
   ```
   https://script.google.com/macros/s/AKfycb.../exec
   ```
   Paste that into `server/config.json`:
   ```json
   {
     "webapp_url": "https://script.google.com/macros/s/AKfycb.../exec",
     "webapp_secret": "z3nAYx7Oo1_7ypnQMSeREuJDRuNTXzGa"
   }
   ```

7. **Restart the server.** On startup it creates one tab per event ("VBS
   2026 (KidsPoint)" and "Youth Summer Revival 2026"), fills in the full
   roster, and from then on updates each person's Status/Checked-In-At
   cell the moment they're checked in.

If you edit the script later (e.g. fix a bug), you need to **Deploy → 
Manage deployments → edit (pencil) → New version → Deploy** for changes
to take effect — just saving the file isn't enough.

If something's misconfigured, the app keeps working in local-only mode —
it never blocks check-ins on the Sheet being reachable. The small status
line at the bottom of the page shows whether the Sheet is currently
connected. After fixing config, you can either restart the server or
POST to `/api/resync-sheet` to retry without a restart.
