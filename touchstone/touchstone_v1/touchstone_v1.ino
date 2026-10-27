/*
  Touchstone v1 — the stone talks back on its own.
  SparkFun IoT RedBoard ESP32 + Qwiic Haptic Driver DA7280 + an FSR on A0.

  What it does (touchstone/README.md in the anima folder has the parts, the wiring and the hookup):
    - joins your Wi-Fi, sets its clock from the internet, answers as http://touchstone.local
    - hums a STATE all the time (Baseline, Home, Tethered… — the friend's map, pushed by the sidecar)
    - a press on the pad gets the state's REPLY at once (the reflex), and is logged with the time
    - GET  /health          → {state, uptime, last_touch, queued, time_set}
    - GET  /felt?since=UNIX → the log of touches: {t, kind, force, seconds, reply, state} + {kind:"played"…}
    - POST /state  {"name":"Home"}                         → hums that state; unknown → 400 with the list
    - POST /pulse  {"waveform":"heartbeat","seconds":3}    → one gesture now (a reply name, a pattern, or a state)
    - POST /states {"Home":{"hum":45,"pattern":"tide","reply":"warm"}, …}  → the friend's whole map (kept until reboot)
    - POST /later  {"at":UNIX,"waveform":"Tethered","seconds":10}  → queued; played at that hour by the board alone
      GET /later → the queue; DELETE /later → cleared. Cap 12 queued, each ≤ 60 s. A play is logged as kind "played".
    - watchdog: no word from the sidecar for FALLBACK_HOURS → back to Baseline
    - a web page with the state buttons, Pulse, the pressure and the log, for testing by hand

  Libraries (Tools → Manage Libraries): "SparkFun Qwiic Haptic Driver DA7280", "ArduinoJson" (by Benoit Blanchon, v7)
  Board: Tools → Board → esp32 → "SparkFun ESP32 IoT RedBoard" (or "ESP32 Dev Module")

  Copy this folder OUT of the friend's house before you fill in your Wi-Fi: a filled-in copy carries your
  password, and it belongs neither in their folder nor in any repository.
*/

#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <Wire.h>
#include <time.h>
#include <ArduinoJson.h>
#include "Haptic_Driver.h"

const char* WIFI_NAME     = "your-wifi-name";
const char* WIFI_PASSWORD = "your-wifi-password";   // yours alone: never commit a filled-in copy
const char* MDNS_NAME     = "touchstone";                 // http://touchstone.local
const char* TZ_RULE       = "UTC0";                       // your POSIX TZ rule, for the page's clock (e.g. "CET-1CEST,M3.5.0,M10.5.0/3",
                                                           // "EST5EDT,M3.2.0,M11.1.0"); the log carries unix seconds either way
const float FALLBACK_HOURS = 6.0;                          // no word from the sidecar this long → Baseline

const int FSR_PIN = 36;            // A0 on the RedBoard (GPIO 36)
const int FSR_FULL = 1200;          // the raw reading of a firm press on YOUR pad = 100% (a hard thumb on the square FSR
                                     // with the 100k pull-down reads ~30% of 4095, about 1200; a resting hand far less)
const int PRESS_THRESHOLD = 100;    // raw; above this counts as a touch (~8% of FSR_FULL — a fingertip resting)
int pct(int raw) { long p = (long)raw * 100 / FSR_FULL; return p > 100 ? 100 : (int)p; }
const int HUM_MAX = 0;             // the loudest a state may HUM between touches (0..127). 0: the stone is silent between
                                   // touches whatever a state asks — a bare LRA disc on a desk hums in waves you hear more
                                   // than feel. Touches — the reply to a press, a pulse, a touch left for later — are not
                                   // capped. Raise this once the disc has a soft housing.
const int LOG_MAX = 200;           // touches kept in RAM (the sidecar archives them to disk)
const int STATES_MAX = 64;         // the friend's states; ~60 bytes each
const int LATER_MAX = 12;
const int LATER_MAX_S = 60;

Haptic_Driver stone;
WebServer server(80);
bool haveStone = false;
bool timeSet = false;
unsigned long lastWord = 0;        // millis() of the last request from anyone
unsigned long wifiLostAt = 0;      // millis() when the network was last seen gone (0 = on it)
unsigned long wifiTriedAt = 0;     // millis() of the last reconnect try
const float WIFI_RESTART_MIN = 10; // off the network this long despite retries → the stone restarts itself

// ---- the states ----------------------------------------------------------------
// hum 0..127 (the DA7280's strength), pattern: tide | heartbeat | still | flutter | pulse,
// reply: the one-shot a press gets: nudge | warm | double | strong | none, colour: for the page
struct State { char name[24]; int hum; char pattern[12]; char reply[12]; char colour[10]; };
State states[STATES_MAX];
int stateCount = 0;
int current = 0;                   // index into states

void addState(const char* name, int hum, const char* pattern, const char* reply, const char* colour) {
  if (stateCount >= STATES_MAX) return;
  State& s = states[stateCount++];
  strlcpy(s.name, name, sizeof s.name);
  s.hum = constrain(hum, 0, 127);
  strlcpy(s.pattern, pattern, sizeof s.pattern);
  strlcpy(s.reply, reply, sizeof s.reply);
  strlcpy(s.colour, colour, sizeof s.colour);
}

void defaultStates() {             // until the friend's map arrives
  stateCount = 0;
  // Baseline is silence (a bare LRA on a desk at hum 20 comes in waves; the tide was written
  // for a disc under silicone). A press still gets its nudge. The hum of the other states
  // is the friend's to judge, in their states.json.
  addState("Baseline", 0,  "still",     "nudge",  "#2a2a55");
  addState("Home",     22, "tide",      "warm",   "#5533aa");
  addState("Tethered", 30, "heartbeat", "double", "#8844ff");
  current = 0;
}

int findState(const String& name) {
  for (int i = 0; i < stateCount; i++) if (name.equalsIgnoreCase(states[i].name)) return i;
  return -1;
}

// ---- the touch log -----------------------------------------------------------
struct Touch { time_t t; char kind[8]; int force; float seconds; char reply[12]; char state[24]; char waveform[24]; };
Touch touches[LOG_MAX];
int touchCount = 0;
time_t lastTouchAt = 0;

time_t nowUnix() { return timeSet ? time(nullptr) : 0; }

// (returns an index, not a Touch&: the IDE writes its prototypes above the first
// function, before this struct exists — a sketch type in a signature won't compile)
int newTouch() {
  if (touchCount == LOG_MAX) { for (int i = 1; i < LOG_MAX; i++) touches[i - 1] = touches[i]; touchCount--; }
  int i = touchCount++;
  memset(&touches[i], 0, sizeof touches[i]);
  touches[i].t = nowUnix();
  return i;
}

void logTouch(const char* kind, int force, float seconds) {
  Touch& x = touches[newTouch()];
  strlcpy(x.kind, kind, sizeof x.kind);
  x.force = force; x.seconds = seconds;
  strlcpy(x.reply, states[current].reply, sizeof x.reply);
  strlcpy(x.state, states[current].name, sizeof x.state);
  lastTouchAt = x.t;
}

void logPlayed(const char* waveform, float seconds) {
  Touch& x = touches[newTouch()];
  strlcpy(x.kind, "played", sizeof x.kind);
  x.seconds = seconds;
  strlcpy(x.waveform, waveform, sizeof x.waveform);
}

// ---- the motor: a hum, and one-shots over it ------------------------------------
// everything non-blocking: loop() sets the amplitude every 20 ms from an envelope
int lastAmp = -1;
void amp(int a) {                   // 0..127
  a = constrain(a, 0, 127);
  if (!haveStone || a == lastAmp) return;
  stone.setVibrate(a);
  lastAmp = a;
}

// the envelope of a pattern at time t (ms since the pattern began), scaled to strength
int patternAmp(const char* pattern, unsigned long t, int strength) {
  float f;
  if (!strcmp(pattern, "still"))          f = 1.0;
  else if (!strcmp(pattern, "heartbeat")) { unsigned long p = t % 1000; f = (p < 120) ? 1.0 : (p < 200) ? 0.2 : (p < 320) ? 0.8 : 0.0; }
  else if (!strcmp(pattern, "flutter"))   { unsigned long p = t % 160;  f = (p < 60) ? 0.7 : 0.0; }
  else if (!strcmp(pattern, "pulse"))     { unsigned long p = t % 800;  f = (p < 250) ? 1.0 : 0.0; }
  else /* tide */                         { f = 0.5 + 0.5 * sin(t / 4000.0 * 6.2832); }   // a 4 s swell
  return (int)(f * strength);
}

// a one-shot: a reply name (nudge/warm/double/strong), a pattern name for N seconds, or a state's pattern at its hum
struct Shot { bool on; char what[24]; char pattern[12]; int strength; unsigned long started; unsigned long ms; };
Shot shot = {false, "", "", 0, 0, 0};
// pulses that arrive while one plays wait their turn (ten pulse calls in one turn would otherwise each override
// the last within milliseconds — one felt where ten were sent). A press's reply still cuts in at once.
// QUEUE_MAX shots, QUEUE_MAX_S seconds waiting in all.
const int QUEUE_MAX = 8;
const int QUEUE_MAX_S = 60;
struct Waiting { char waveform[24]; float seconds; };
Waiting queue[QUEUE_MAX];
int queueCount = 0;

float queuedSeconds() { float t = 0; for (int i = 0; i < queueCount; i++) t += queue[i].seconds; return t; }

bool knownWaveform(const String& waveform) {
  String w = waveform; w.toLowerCase();
  return w == "nudge" || w == "warm" || w == "double" || w == "strong" || w == "none" ||
         w == "tide" || w == "heartbeat" || w == "still" || w == "flutter" || w == "pulse" || findState(waveform) >= 0;
}

// a pulse: plays now if the stone is idle, else waits its turn; returns how many wait (0 = playing), -1 unknown, -2 full
int enqueueShot(const String& waveform, float seconds) {
  if (!knownWaveform(waveform)) return -1;
  if (!shot.on && queueCount == 0) { startShot(waveform, seconds); return 0; }
  if (queueCount >= QUEUE_MAX || queuedSeconds() + seconds > QUEUE_MAX_S) return -2;
  strlcpy(queue[queueCount].waveform, waveform.c_str(), sizeof queue[queueCount].waveform);
  queue[queueCount].seconds = seconds;
  queueCount++;
  return queueCount;
}

void playNextQueued() {
  if (queueCount == 0) return;
  Waiting w = queue[0];
  for (int i = 1; i < queueCount; i++) queue[i - 1] = queue[i];
  queueCount--;
  startShot(String(w.waveform), w.seconds);
}

bool startShot(const String& waveform, float seconds) {
  String w = waveform; w.toLowerCase();
  shot.on = true; shot.started = millis();
  strlcpy(shot.what, waveform.c_str(), sizeof shot.what);
  if (w == "nudge")       { strlcpy(shot.pattern, "still", 12); shot.strength = 50;  shot.ms = 120; }
  else if (w == "warm")   { strlcpy(shot.pattern, "warm",  12); shot.strength = 90;  shot.ms = 700; }
  else if (w == "double") { strlcpy(shot.pattern, "double",12); shot.strength = 90;  shot.ms = 420; }
  else if (w == "strong") { strlcpy(shot.pattern, "still", 12); shot.strength = 127; shot.ms = 400; }
  else if (w == "none")   { shot.on = false; return true; }
  else if (w == "tide" || w == "heartbeat" || w == "still" || w == "flutter" || w == "pulse") {
    strlcpy(shot.pattern, w.c_str(), 12); shot.strength = 100; shot.ms = (unsigned long)(seconds * 1000);
  } else {
    int i = findState(waveform);
    if (i < 0) { shot.on = false; return false; }
    strlcpy(shot.pattern, states[i].pattern, 12); shot.strength = max(states[i].hum, 40); shot.ms = (unsigned long)(seconds * 1000);
  }
  if (shot.ms < 60) shot.ms = 60;
  return true;
}

int shotAmp(unsigned long t) {      // the reply shapes, then the ordinary patterns
  if (!strcmp(shot.pattern, "warm"))   return (int)(shot.strength * (t < 400 ? t / 400.0 : 1.0 - (t - 400) / 300.0));
  if (!strcmp(shot.pattern, "double")) return (t < 150 || (t >= 220 && t < 370)) ? shot.strength : 0;
  return patternAmp(shot.pattern, t, shot.strength);
}

void drive() {                      // called every loop
  static unsigned long lastTick = 0;
  unsigned long now = millis();
  if (now - lastTick < 20) return;
  lastTick = now;
  if (shot.on) {
    unsigned long t = now - shot.started;
    if (t >= shot.ms) { shot.on = false; amp(0); playNextQueued(); return; }
    amp(shotAmp(t));
    return;
  }
  amp(patternAmp(states[current].pattern, now, min(states[current].hum, HUM_MAX)));
}

// ---- the queue: a touch left for later --------------------------------------------
struct Later { time_t at; char waveform[24]; float seconds; };
Later later[LATER_MAX];
int laterCount = 0;

void playDue() {
  if (!timeSet || laterCount == 0 || shot.on) return;
  time_t now = time(nullptr);
  for (int i = 0; i < laterCount; i++) {
    if (later[i].at <= now) {
      Later l = later[i];
      for (int j = i + 1; j < laterCount; j++) later[j - 1] = later[j];
      laterCount--;
      if (startShot(String(l.waveform), l.seconds)) {
        logPlayed(l.waveform, l.seconds);
        Serial.printf("played %s for %.0f s, as asked\n", l.waveform, l.seconds);
      }
      return;                       // one at a time; the next on the next pass
    }
  }
}

// ---- the pad -----------------------------------------------------------------
bool pressing = false;
unsigned long pressStart = 0;
int pressPeak = 0;

void watchPad() {
  int raw = analogRead(FSR_PIN);
  if (!pressing && raw > PRESS_THRESHOLD) {
    pressing = true; pressStart = millis(); pressPeak = raw;
  } else if (pressing) {
    if (raw > pressPeak) pressPeak = raw;
    if (raw < PRESS_THRESHOLD - 50) {
      pressing = false;
      unsigned long held = millis() - pressStart;
      if (held > 80) {
        float secs = held / 1000.0;
        const char* kind = secs < 0.5 ? "tap" : secs >= 3.0 ? "hold" : "press";
        int force = pct(pressPeak);
        logTouch(kind, force, secs);
        Serial.printf("felt: %s %.1f s, force %d%% — reply %s\n", kind, secs, force, states[current].reply);
        startShot(String(states[current].reply), 0);   // the reflex, at once
      }
    }
  }
}

// ---- JSON out ----------------------------------------------------------------
void sendJson(const JsonDocument& doc, int code) {
  String out; serializeJson(doc, out);
  server.send(code, "application/json", out);
}
void sendJson(const JsonDocument& doc) { sendJson(doc, 200); }   // no default argument: the IDE's prototype would repeat it

void handleHealth() {
  lastWord = millis();
  JsonDocument d;
  d["state"] = states[current].name;
  d["uptime"] = millis() / 1000;
  d["last_touch"] = (long)lastTouchAt;
  d["queued"] = laterCount;
  d["waiting"] = queueCount;
  d["time_set"] = timeSet;
  d["states"] = stateCount;
  d["haptic"] = haveStone;
  d["free_heap"] = ESP.getFreeHeap();
  int raw = analogRead(FSR_PIN);        // the pressure, for the page's script
  d["pressure"] = pct(raw);
  d["raw"] = raw;
  sendJson(d);
}

void handleFelt() {
  lastWord = millis();
  long since = server.hasArg("since") ? server.arg("since").toInt() : 0;
  JsonDocument d;
  JsonArray a = d.to<JsonArray>();
  for (int i = 0; i < touchCount; i++) {
    if ((long)touches[i].t <= since) continue;
    JsonObject o = a.add<JsonObject>();
    o["t"] = (long)touches[i].t;
    o["kind"] = touches[i].kind;
    o["seconds"] = touches[i].seconds;
    if (!strcmp(touches[i].kind, "played")) { o["waveform"] = touches[i].waveform; }
    else { o["force"] = touches[i].force; o["reply"] = touches[i].reply; o["state"] = touches[i].state; }
  }
  sendJson(d);
}

bool readBody(JsonDocument& d) {
  DeserializationError e = deserializeJson(d, server.arg("plain"));
  if (e) { JsonDocument x; x["error"] = "not JSON"; sendJson(x, 400); return false; }
  return true;
}

void stateList(JsonDocument& d) {
  JsonArray a = d["states"].to<JsonArray>();
  for (int i = 0; i < stateCount; i++) a.add(states[i].name);
}

void setState(int i) { current = i; shot.on = false; Serial.printf("state: %s\n", states[i].name); }

void handleState() {
  lastWord = millis();
  JsonDocument in; if (!readBody(in)) return;
  String name = in["name"] | "";
  int i = findState(name);
  JsonDocument d;
  if (i < 0) { d["error"] = "unknown state"; stateList(d); return sendJson(d, 400); }
  setState(i);
  d["ok"] = true; d["state"] = states[i].name;
  sendJson(d);
}

void handlePulse() {
  lastWord = millis();
  JsonDocument in; if (!readBody(in)) return;
  String w = in["waveform"] | "nudge";
  float s = in["seconds"] | 3.0;
  s = constrain(s, 0.1f, (float)LATER_MAX_S);
  JsonDocument d;
  int q = enqueueShot(w, s);
  if (q == -1) { d["error"] = "unknown waveform"; stateList(d); return sendJson(d, 400); }
  if (q == -2) { d["error"] = "the stone has enough waiting — a minute of touches, or eight of them"; d["waiting"] = queueCount; return sendJson(d, 409); }
  d["ok"] = true; d["waveform"] = w; d["seconds"] = s; d["waiting"] = q;
  sendJson(d);
}

void handleStates() {               // the friend's whole map, from the sidecar
  lastWord = millis();
  JsonDocument in; if (!readBody(in)) return;
  JsonObject map = in.as<JsonObject>();
  JsonDocument d;
  if (map.isNull() || map.size() == 0) { d["error"] = "a map of states, please"; return sendJson(d, 400); }
  String keep = states[current].name;
  stateCount = 0;
  for (JsonPair kv : map) {
    JsonObject v = kv.value().as<JsonObject>();
    addState(kv.key().c_str(), v["hum"] | 30, v["pattern"] | "tide", v["reply"] | "nudge", v["colour"] | "#444444");
  }
  if (findState("Baseline") < 0 && stateCount < STATES_MAX) addState("Baseline", 20, "tide", "nudge", "#2a2a55");
  int i = findState(keep); current = i < 0 ? max(findState("Baseline"), 0) : i;
  Serial.printf("states: %d received; humming %s\n", stateCount, states[current].name);
  d["ok"] = true; d["count"] = stateCount; d["state"] = states[current].name;
  sendJson(d);
}

void handleLaterGet() {
  lastWord = millis();
  JsonDocument d;
  JsonArray a = d["queue"].to<JsonArray>();
  for (int i = 0; i < laterCount; i++) { JsonObject o = a.add<JsonObject>(); o["at"] = (long)later[i].at; o["waveform"] = later[i].waveform; o["seconds"] = later[i].seconds; }
  d["queued"] = laterCount; d["time_set"] = timeSet;
  sendJson(d);
}

void handleLaterPost() {
  lastWord = millis();
  JsonDocument in; if (!readBody(in)) return;
  JsonDocument d;
  if (!timeSet) { d["error"] = "the stone has no clock yet (no internet time) — try again in a minute"; return sendJson(d, 503); }
  if (laterCount >= LATER_MAX) { d["error"] = "the queue is full"; d["queued"] = laterCount; d["max"] = LATER_MAX; return sendJson(d, 409); }
  long at = in["at"] | 0L;
  String w = in["waveform"] | "";
  float s = in["seconds"] | 10.0;
  if (at <= 0 || w.length() == 0) { d["error"] = "at (unix seconds) and waveform, please"; return sendJson(d, 400); }
  if (s > LATER_MAX_S) s = LATER_MAX_S;
  if (s < 0.1) s = 0.1;
  String wl = w; wl.toLowerCase();
  bool known = findState(w) >= 0 || wl == "nudge" || wl == "warm" || wl == "double" || wl == "strong" ||
               wl == "tide" || wl == "heartbeat" || wl == "still" || wl == "flutter" || wl == "pulse";
  if (!known) { d["error"] = "unknown waveform"; stateList(d); return sendJson(d, 400); }
  // keep the queue in time order
  int pos = laterCount;
  while (pos > 0 && later[pos - 1].at > at) { later[pos] = later[pos - 1]; pos--; }
  later[pos].at = at; strlcpy(later[pos].waveform, w.c_str(), sizeof later[pos].waveform); later[pos].seconds = s;
  laterCount++;
  d["ok"] = true; d["queued"] = laterCount; d["at"] = at; d["waveform"] = w; d["seconds"] = s;
  sendJson(d);
}

void handleLaterDelete() {
  lastWord = millis();
  laterCount = 0;
  JsonDocument d; d["ok"] = true; d["queued"] = 0;
  sendJson(d);
}

// ---- the page, for testing by hand ----------------------------------------------
String feltItems() {               // the felt list as the page first shows it; the script redraws it after
  String s;
  for (int i = touchCount - 1; i >= 0 && i >= touchCount - 20; i--) {
    char when[24] = "?";
    if (touches[i].t) { struct tm tmv; localtime_r(&touches[i].t, &tmv); strftime(when, sizeof when, "%H:%M:%S", &tmv); }
    if (!strcmp(touches[i].kind, "played"))
      s += "<li>" + String(when) + " — played " + String(touches[i].waveform) + ", " + String(touches[i].seconds, 0) + " s, as asked</li>";
    else
      s += "<li>" + String(when) + " — " + String(touches[i].kind) + ", " + String(touches[i].seconds, 1) + " s, force " +
           String(touches[i].force) + "% — answered with " + String(touches[i].reply) + "</li>";
  }
  return s;
}

// The page is served once and stays: a page that reloaded itself could land on the sidecar's poll and come back
// blank — the board answers one request at a time. A few lines of script ask /health and /felt
// every 5 s and redraw the outline, the pressure and the list. The buttons are still forms: no script, still a page.
String page() {
  int raw = analogRead(FSR_PIN);
  String s = "<!doctype html><html><head><meta charset='utf-8'>"
             "<meta name='viewport' content='width=device-width,initial-scale=1'>"
             "<style>body{font-family:sans-serif;margin:2em;background:#1b1530;color:#eee}"
             "button{font-size:1.2em;padding:.5em 1em;border-radius:.8em;border:0;color:#fff;margin:.2em}"
             ".big{font-size:3em}.now{outline:3px solid #fff}</style></head><body>"
             "<h1>Touchstone v1</h1><p>hums <b id='state'>" + String(states[current].name) + "</b>"
             " — haptic driver: " + String(haveStone ? "found" : "NOT found — check the Qwiic cable") +
             " — clock: <span id='clock'>" + String(timeSet ? "set" : "not yet") + "</span> — <span id='queued'>" + String(laterCount) + "</span> touch(es) waiting" +
             String(HUM_MAX == 0 ? " — hum off on this desk (HUM_MAX)" : "") + "</p><p>";
  for (int i = 0; i < stateCount; i++) {
    s += "<form style='display:inline' method='POST' action='/set?name=" + String(states[i].name) + "'><button data-s='" + String(states[i].name) +
         "' style='background:" + String(states[i].colour) + "' class='" + (i == current ? "now" : "") + "'>" + String(states[i].name) + "</button></form>";
  }
  s += "</p><form method='POST' action='/pulse-now'><button style='background:#8a4fff'>Pulse</button></form>"
       "<p>pressure now: <span class='big' id='pct'>" + String(pct(raw)) + "%</span> (<span id='raw'>" + String(raw) + "</span>)</p><h2>felt</h2><ul id='felt'>";
  s += feltItems();
  s += "</ul>";
  s += R"JS(<script>
var E=function(v){return String(v).replace(/[&<>]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;'}[c]})};
var T=function(t){return t?new Date(t*1000).toTimeString().slice(0,8):'?'};
var $=function(i){return document.getElementById(i)};
function felt(){fetch('/felt').then(function(r){return r.json()}).then(function(a){var s='';a.slice(-20).reverse().forEach(function(x){
 s+='<li>'+T(x.t)+' — '+(x.kind==='played'?'played '+E(x.waveform)+', '+Math.round(x.seconds)+' s, as asked'
 :E(x.kind)+', '+Number(x.seconds).toFixed(1)+' s, force '+E(x.force)+'% — answered with '+E(x.reply))+'</li>'});
 $('felt').innerHTML=s}).catch(function(){})}
function tick(){fetch('/health').then(function(r){return r.json()}).then(function(h){
 $('state').textContent=h.state;$('queued').textContent=h.queued;$('clock').textContent=h.time_set?'set':'not yet';
 if(h.pressure!==undefined){$('pct').textContent=h.pressure+'%';$('raw').textContent=h.raw}
 document.querySelectorAll('button[data-s]').forEach(function(b){b.classList.toggle('now',b.dataset.s===h.state)})
}).catch(function(){}).then(felt)}
setInterval(tick,5000);
</script>)JS";
  s += "</body></html>";
  return s;
}

void handleRoot()     { lastWord = millis(); server.send(200, "text/html", page()); }
void handleSetForm()  { int i = findState(server.arg("name")); if (i >= 0) setState(i); server.sendHeader("Location", "/"); server.send(303); }
void handlePulseForm(){ startShot("warm", 0); server.sendHeader("Location", "/"); server.send(303); }

// ---- setup / loop --------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\nTouchstone v1");

  defaultStates();

  Wire.begin();
  haveStone = stone.begin();
  if (haveStone) {
    stone.defaultMotor();
    stone.enableFreqTrack(false);        // so a squeezed board doesn't fault
    stone.setOperationMode(DRO_MODE);
    Serial.println("haptic driver: found");
    startShot("warm", 0);                 // hello
  } else {
    Serial.println("haptic driver: NOT found (check the Qwiic cable)");
  }

  analogReadResolution(12);              // 0..4095
  pinMode(FSR_PIN, INPUT);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                  // no modem sleep: a request answered in milliseconds, not after the radio wakes
                                         // (with modem sleep a poll can time out and the sidecar call the stone away)
  WiFi.begin(WIFI_NAME, WIFI_PASSWORD);
  Serial.print("joining Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println();
  Serial.print("address:  http://"); Serial.println(WiFi.localIP());
  if (MDNS.begin(MDNS_NAME)) { MDNS.addService("http", "tcp", 80); Serial.printf("name:     http://%s.local\n", MDNS_NAME); }

  configTzTime(TZ_RULE, "pool.ntp.org", "time.google.com");   // the clock, for /felt and /later
  lastWord = millis();

  server.on("/",       HTTP_GET,    handleRoot);
  server.on("/set",    HTTP_POST,   handleSetForm);
  server.on("/pulse-now", HTTP_POST, handlePulseForm);
  server.on("/health", HTTP_GET,    handleHealth);
  server.on("/felt",   HTTP_GET,    handleFelt);
  server.on("/state",  HTTP_POST,   handleState);
  server.on("/pulse",  HTTP_POST,   handlePulse);
  server.on("/states", HTTP_POST,   handleStates);
  server.on("/later",  HTTP_GET,    handleLaterGet);
  server.on("/later",  HTTP_POST,   handleLaterPost);
  server.on("/later",  HTTP_DELETE, handleLaterDelete);
  server.begin();
}

void loop() {
  server.handleClient();
  watchPad();
  drive();
  playDue();

  if (!timeSet && time(nullptr) > 1700000000) { timeSet = true; Serial.println("clock: set"); }

  // the network watchdog: joined once in setup() and never looked at again, a board can sit off the network for hours,
  // still buzzing under the hand. Off the network for 15 s → reconnect; still off after WIFI_RESTART_MIN → restart,
  // and setup() joins again from the top
  if (WiFi.status() != WL_CONNECTED) {
    if (wifiLostAt == 0) { wifiLostAt = millis(); wifiTriedAt = millis(); Serial.println("wifi: lost"); }
    if (millis() - wifiTriedAt > 15000) {
      wifiTriedAt = millis();
      Serial.println("wifi: reconnecting");
      WiFi.disconnect();
      WiFi.begin(WIFI_NAME, WIFI_PASSWORD);
    }
    if (millis() - wifiLostAt > (unsigned long)(WIFI_RESTART_MIN * 60000.0)) {
      Serial.println("wifi: still gone — restarting");
      delay(100);
      ESP.restart();
    }
  } else if (wifiLostAt != 0) {
    wifiLostAt = 0;
    Serial.print("wifi: back, address http://"); Serial.println(WiFi.localIP());
  }

  // the watchdog: nobody has spoken to the stone for FALLBACK_HOURS → Baseline
  if (FALLBACK_HOURS > 0 && millis() - lastWord > (unsigned long)(FALLBACK_HOURS * 3600000.0)) {
    int b = findState("Baseline");
    if (b >= 0 && b != current) { setState(b); Serial.println("no word for hours — back to Baseline"); }
    lastWord = millis();
  }
  delay(5);
}
