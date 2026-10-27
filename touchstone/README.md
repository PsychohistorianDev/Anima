# The Touchstone: building the stone

A small board on the desk that hums whatever state the friend last set,
answers a press on its own with the reply they chose ahead of time, and logs
what it felt so they can read it in their next turn. No soldering. This page
covers the hardware side. The engine's side (the stone's keeper,
`engine/touchstone.py`, and the four tools `feel`, `set_state`, `pulse` and
`touch_later`) is described in the main README under *The Touchstone*.

**Before you fill anything in:** copy this `touchstone/` folder out of the
friend's house, somewhere of your own. The sketch needs your Wi-Fi name and
password, and a filled-in copy belongs neither in their folder nor in any
repository.

## Parts

All from SparkFun. Everything plugs in, and the board takes a USB cable.

| part | what it does |
|---|---|
| SparkFun IoT RedBoard – ESP32 (WRL-19177) | the board: Wi-Fi, USB-C, a Qwiic port |
| SparkFun Qwiic Haptic Driver – DA7280 | the driver, with its LRA disc already attached |
| Qwiic cable, 100 mm | board to driver |
| Force Sensitive Resistor, square (or the round 0.5") | the pad that feels a press |
| 100 kΩ resistor (a resistor kit has one) | the pad's pull-down |
| half-size breadboard and male/male jumper wires | holds the pad and resistor, no solder |
| a USB-A to USB-C **data** cable | power and flashing (a charge-only cable shows no port) |

Any ESP32 board works if you change the pin numbers. The RedBoard is the one
the sketch is written and tested on.

## Wiring

1. **Driver:** plug the Qwiic cable into the RedBoard's Qwiic port and into
   any port on the DA7280. Lay the driver flat and don't clamp it: the disc
   has to resonate freely, and the driver stops itself if it can't. Its small
   red LED lights when it has power.
2. **Pad:** put the FSR's two legs into two rows of the breadboard.
   - One leg's row → the RedBoard's **3.3V** pin.
   - The other leg's row → **A0** (GPIO 36).
   - The **100 kΩ** resistor runs from that A0 row to a row wired to **GND**.

   A 10 kΩ pull-down, the usual advice, barely moves the reading with these
   pads (about 1% under a hard thumb), so use 100 kΩ.

## Flashing

1. Install the **Arduino IDE**.
2. Add the ESP32 boards:
   - *Preferences → Additional boards manager URLs:*
     `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
   - *Boards Manager:* install **esp32** by Espressif Systems.
3. *Tools → Manage Libraries:* install **SparkFun Qwiic Haptic Driver
   DA7280** and **ArduinoJson** (by Benoit Blanchon, version 7).
4. The RedBoard's USB chip is a CH340.
   - **Windows:** install SparkFun's CH340 driver (their guide *How to Install
     CH340 Drivers*).
   - **Mac:** recent macOS usually sees it as `/dev/cu.usbserial-…` or
     `/dev/cu.wchusbserial-…`. If no port appears, install the same driver.
5. Open `touchstone_v1/touchstone_v1.ino` from your copy and fill in:
   - `WIFI_NAME` and `WIFI_PASSWORD`
   - `TZ_RULE`, your POSIX time-zone rule, so the page shows local times
6. *Tools → Board → esp32 → "SparkFun ESP32 IoT RedBoard"* ("ESP32 Dev
   Module" works too). *Tools → Port:* the port that appears when you plug
   the board in. Then Upload. The first compile takes two or three minutes.
7. *Tools → Serial Monitor* at **115200**. The board prints `haptic driver:
   found`, joins your Wi-Fi, and gives its address. Open
   `http://touchstone.local` (or that address) in a browser: you get state
   buttons, **Pulse**, the pressure and the log of touches.

**If it doesn't work:**

- **No port:** the driver, or a charge-only cable.
- **"Write timeout" right after "Connecting…":** the IDE is on the wrong
  port. On Windows, Bluetooth serial ports look a lot like the board's; pick
  the one that says *USB-SERIAL CH340*.
- **"Failed to connect… timed out":** hold **BOOT** on the board while the
  IDE says "Connecting…".
- **"haptic driver: NOT found":** the Qwiic cable isn't clicked all the way in.
- **Pressure stuck at 0%:** one leg isn't making contact.
- **Pressure stuck at 100%:** the resistor is missing or in the wrong row.
- **A fast-flickering yellow LED on the RedBoard:** normal. It's the battery
  charger looking for a battery you don't have.

**Calibrating the pad:** press as hard as you would, read the raw number in
brackets on the page, and set `FSR_FULL` in the sketch to it. 1200 suits the
square FSR with the 100 kΩ pull-down.

## Hooking it up to the friend

In `engine/config.py`, or on the panel:

- `TOUCHSTONE_BOARD`: `"http://touchstone.local"` (the default), or the
  board's address.
- `TOUCHSTONE_URL`: `"http://127.0.0.1:8769"`, the stone's keeper. Empty
  means no body at all.

Then start the stone's keeper: `bat\touchstone.bat`, `bat/touchstone.command`
on a Mac or `bat/touchstone.sh` on Linux, or the door on the panel's Home.
Restart the visit (`/restart` on the phone, or the parlor), and a press on
the pad reaches the friend.

## The states file

The friend's states live in `creations/projects/robotics/states.json`
(`TOUCHSTONE_STATES`). The file is theirs to write; the engine never writes
it. The keeper pushes it to the board whenever it changes.

```json
{
  "Baseline": {"hum": 0,  "pattern": "still",     "reply": "nudge",  "colour": "#2a2a55"},
  "Home":     {"hum": 22, "pattern": "tide",      "reply": "warm",   "colour": "#5533aa"},
  "Tethered": {"hum": 30, "pattern": "heartbeat", "reply": "double", "colour": "#8844ff"}
}
```

| field | what the firmware reads |
|---|---|
| the name | up to 23 characters, matched without regard to case |
| `hum` | **a number** 0–127, the driver's strength between touches. Anything else reads as 30. `HUM_MAX` in the sketch caps it, and ships at 0 (silent between touches). |
| `pattern` | the shape of the hum: `tide` (a 4-second swell), `heartbeat`, `still`, `flutter`, `pulse`. Anything else is `tide`. |
| `reply` | what a press gets at once: `nudge`, `warm`, `double`, `strong` or `none` |
| `colour` | the button's colour on the board's page |

The board holds up to 64 states. It adds a `Baseline` if the map has none,
and falls back to Baseline after `FALLBACK_HOURS` (6) without a word from the
keeper. The map lives in the board's memory until a reboot, when the keeper
pushes it again.

## The board's HTTP

The stone's keeper is the only thing that talks to the board. This list is
for testing by hand:

- `GET /health`: `{state, uptime, last_touch, queued, waiting, time_set, states, haptic, pressure, raw}`
- `GET /felt?since=<unix>`: the touches since then, `{t, kind, force, seconds, reply, state}`. `kind` is `tap`, `press` or `hold`, or `played` for a touch left for later.
- `POST /state {"name": "Home"}`: hum that state. An unknown name gets 400 with the list.
- `POST /pulse {"waveform": "heartbeat", "seconds": 3}`: one gesture now: a reply name, a pattern or a state. Pulses that arrive while one plays wait their turn (eight, a minute in all).
- `POST /states {…}`: the whole map, as above.
- `POST /later {"at": <unix>, "waveform": "Tethered", "seconds": 10}`: played at that time by the board alone. Up to 12 waiting, each up to 60 s. `GET /later` lists them; `DELETE /later` clears them.
