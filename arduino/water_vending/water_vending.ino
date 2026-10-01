#include <Arduino.h> // Use Arduino pins, timing, interrupts, and serial.
#include <stdlib.h> // Convert validated decimal commands.
#include <string.h> // Split and compare command words.
#include "config.h" // Load installer settings.
volatile uint32_t pulses[2] = {0, 0}; // Counters changed by interrupts.
volatile uint32_t lastUs[2] = {0, 0}; // Previous accepted pulse times.
void pulse(uint8_t c) { // Count one channel's flow pulses.
  uint32_t now = micros(); // Read the microsecond clock.
  if (now - lastUs[c] >= 250) { // Reject very closely spaced electrical glitches.
    lastUs[c] = now; // Remember this accepted pulse.
    pulses[c]++; // Add one measured pulse.
  } // End glitch check.
} // End pulse handler.
void leftISR() { pulse(0); } // Interrupt wrapper for the left sensor.
void rightISR() { pulse(1); } // Interrupt wrapper for the right sensor.
enum State { IDLE, OPENING, FILLING, CLOSING, SETTLING, PAUSED, DONE }; // Simple channel states.
const char* names[] = {"IDLE", "OPENING", "FILLING", "CLOSING", "SETTLING", "PAUSED", "DONE"}; // Printable state names.
struct Channel { // Keep each channel's cycle information together.
  State state; // Current channel state.
  uint32_t target, ml, started, changed, previous, lastFlow; // Volume and timing fields.
  const char* issue; // Most recent reason for an abnormal stop.
}; // End channel definition.
Channel channels[2] = {}; // Start both channels with zeroed fields.
char rx[96]; // Fixed-size command buffer.
uint8_t used = 0; // Number of buffered characters.
bool overflow = false; // Discard an entire oversized command.
uint32_t lastHost = 0, lastReport = 0; // Heartbeat and report clocks.
void valve(uint8_t pin, bool open) { // Translate open/closed into driver polarity.
  digitalWrite(pin, (open == ACTIVE_HIGH) ? HIGH : LOW); // Set the valve driver output.
} // End valve helper.
uint32_t readCount(uint8_t c) { // Read the interrupt counter atomically on an 8-bit AVR.
  noInterrupts(); // Prevent a pulse interrupt during this read.
  uint32_t value = pulses[c]; // Copy all four bytes consistently.
  interrupts(); // Re-enable pulse interrupts.
  return value; // Return the stable copy.
} // End atomic read.
void report(uint8_t c) { // Report one channel to the Pi.
  Serial.print("CH,"); Serial.print(c); Serial.print(','); // Start channel record.
  Serial.print(names[channels[c].state]); Serial.print(','); // Include current state.
  Serial.print(channels[c].ml); Serial.print(','); // Include delivered millilitres.
  Serial.print(channels[c].target); Serial.print(','); // Include requested millilitres.
  Serial.println(channels[c].issue); // Finish with issue code and newline.
} // End report.
void stop(uint8_t c, const char* reason) { // Stop water and enter a trailing-flow interval.
  valve(SOL_PIN[c], false); // Immediately shut the solenoid.
  valve(BALL_PIN[c], false); // Remove power so the auto-return ball valve closes.
  channels[c].state = SETTLING; // Keep measuring trailing flow before reporting completion.
  channels[c].changed = millis(); // Start settling timer.
  channels[c].issue = reason; // Preserve why the channel stopped.
} // End stop helper.
bool number(const char* s, uint32_t& value) { // Validate an unsigned decimal field.
  if (!s || !*s || strlen(s) > 8) return false; // Reject missing and excessively long numbers.
  for (const char* p = s; *p; p++) if (*p < '0' || *p > '9') return false; // Reject signs and trailing junk.
  value = strtoul(s, NULL, 10); // Convert the already validated digits.
  return true; // Accept the value.
} // End numeric validation.
void command(char* line) { // Process one complete serial line.
  if (strstr(line, ",,") || (strlen(line) && line[strlen(line)-1] == ',')) { Serial.println("ERR,FORMAT"); return; } // Reject empty fields instead of letting strtok hide them.
  char* verb = strtok(line, ","); // Extract command name.
  char* channelText = strtok(NULL, ","); // Extract optional channel.
  char* amountText = strtok(NULL, ","); // Extract optional target.
  char* extra = strtok(NULL, ","); // Detect excess fields.
  if (!verb) return; // Ignore an empty line.
  if (!strcmp(verb, "PING") && !channelText) { lastHost = millis(); Serial.println("PONG"); return; } // Accept heartbeat.
  if (!strcmp(verb, "STATUS") && !channelText) { report(0); report(1); return; } // Report both channels.
  if (!strcmp(verb, "STOP") && !channelText) { // Stop any unfinished cycles.
    for (uint8_t c = 0; c < 2; c++) if (channels[c].state != IDLE && channels[c].state != DONE) stop(c, "CANCELLED"); // Close active or paused channels.
    Serial.println("ACK,STOP"); return; // Confirm the stop command.
  } // End global stop.
  uint32_t c, target; // Hold parsed channel and volume.
  if (!number(channelText, c) || c > 1 || extra) { Serial.println("ERR,FORMAT"); return; } // Validate channel and field count.
  Channel& ch = channels[c]; // Refer to the requested channel.
  if (!strcmp(verb, "START")) { // Begin one new fill.
    if (!number(amountText, target) || target < 100 || target > MAX_TARGET_ML) { Serial.println("ERR,TARGET"); return; } // Validate volume.
    if (ch.state != IDLE && ch.state != DONE) { Serial.println("ERR,BUSY"); return; } // Never reset an active cycle.
    noInterrupts(); pulses[c] = 0; interrupts(); // Clear this channel's counter safely.
    ch.target = target; ch.ml = 0; ch.previous = 0; ch.issue = "NONE"; // Initialize cycle values.
    ch.started = ch.changed = ch.lastFlow = millis(); // Initialize all cycle clocks.
    ch.state = OPENING; valve(SOL_PIN[c], true); // Open solenoid first.
    lastHost = millis(); // Start heartbeat allowance.
  } else if (!strcmp(verb, "PAUSE") && !amountText && (ch.state == OPENING || ch.state == FILLING || ch.state == CLOSING)) { // Pause a dispensing channel.
    valve(SOL_PIN[c], false); valve(BALL_PIN[c], false); // Shut both valve commands.
    ch.state = PAUSED; ch.changed = millis(); // Retain target and pulse counter while paused.
  } else if (!strcmp(verb, "RESUME") && !amountText && ch.state == PAUSED) { // Continue an existing fill.
    if (millis() - ch.changed < BALL_CLOSE_MS) { Serial.println("ERR,WAIT_CLOSE"); return; } // Wait for auto-return valve to close before reopening.
    if (ch.ml >= ch.target) stop(c, "NONE"); // Do not reopen a jar that already reached its target.
    else { ch.state = OPENING; ch.changed = ch.lastFlow = millis(); valve(SOL_PIN[c], true); } // Restart opening with preserved volume.
  } else { Serial.println("ERR,STATE"); return; } // Refuse unsupported command/state combinations.
  Serial.print("ACK,"); Serial.print(verb); Serial.print(','); Serial.println(c); // Confirm accepted command.
  report(c); // Immediately publish its resulting state.
} // End command processor.
void setup() { // Configure the Mega after reset.
  for (uint8_t c = 0; c < 2; c++) { // Initialize both channels.
    valve(SOL_PIN[c], false); valve(BALL_PIN[c], false); // Set closed output latches before changing pin direction.
    pinMode(SOL_PIN[c], OUTPUT); pinMode(BALL_PIN[c], OUTPUT); // Enable driver outputs.
    pinMode(FLOW_PIN[c], INPUT_PULLUP); // Enable flow sensor inputs; confirm sensor electrical compatibility.
    channels[c].state = IDLE; channels[c].issue = "NONE"; // Initialize printable channel state.
  } // End channel initialization.
  attachInterrupt(digitalPinToInterrupt(FLOW_PIN[0]), leftISR, RISING); // Count left sensor edges.
  attachInterrupt(digitalPinToInterrupt(FLOW_PIN[1]), rightISR, RISING); // Count right sensor edges.
  Serial.begin(115200); Serial.println("READY,1"); // Start serial and announce protocol version.
} // End startup.
void loop() { // Run frequently without blocking delays.
  uint8_t budget = 32; // Limit serial work per pass so valve checks cannot starve.
  while (budget-- && Serial.available()) { // Read a bounded batch of incoming bytes.
    char b = Serial.read(); // Get next byte.
    if (b == '\r') continue; // Ignore carriage returns.
    if (b == '\n') { // Process only complete lines.
      rx[used] = 0; // Add a C-string terminator.
      if (!overflow) command(rx); else Serial.println("ERR,OVERFLOW"); // Never execute truncated commands.
      used = 0; overflow = false; // Reset input buffer.
    } else if (used < sizeof(rx) - 1 && !overflow) rx[used++] = b; // Store a valid byte.
    else overflow = true; // Discard until newline if too long.
  } // End serial batch.
  uint32_t now = millis(); // Read time once for this control pass.
  for (uint8_t c = 0; c < 2; c++) { // Service each channel independently.
    Channel& ch = channels[c]; // Access this channel's fields.
    uint32_t count = readCount(c); // Snapshot total pulses.
    ch.ml = (uint32_t)(count * 1000.0f / PULSES_PER_LITRE[c] + 0.5f); // Convert cumulative pulses to rounded millilitres.
    if (count != ch.previous) { ch.previous = count; ch.lastFlow = now; } // Remember most recent flow activity.
    bool active = ch.state != IDLE && ch.state != DONE && ch.state != SETTLING; // Identify unfinished controllable states.
    if (active && now - lastHost > HOST_TIMEOUT_MS) stop(c, "HOST_LOST"); // Shut down on missing Pi heartbeat.
    else if (active && now - ch.started > MAX_RUN_MS) stop(c, "MAX_TIME"); // Bound even a paused or stalled fill.
    if (ch.state == OPENING && now - ch.changed >= OPEN_DELAY_MS) { // Wait briefly after solenoid opening.
      valve(BALL_PIN[c], true); ch.state = FILLING; // Power ball valve open and begin normal filling.
    } // End opening step.
    if (ch.state == FILLING || ch.state == CLOSING) { // Check all water-moving states.
      if (ch.ml >= ch.target) stop(c, "NONE"); // Shut solenoid at requested measured volume.
      else if (now - ch.lastFlow > NO_FLOW_MS) stop(c, "NO_FLOW"); // Stop a stalled sensor or water supply.
      else if (ch.state == FILLING && ch.ml >= ch.target * 9UL / 10UL) { // Apply initial fixed 90-percent rule.
        valve(BALL_PIN[c], false); ch.state = CLOSING; ch.changed = now; // Begin gentle ball-valve closure.
      } else if (ch.state == CLOSING && now - ch.changed >= BALL_CLOSE_MS) { // Wait rated maximum closing time.
        stop(c, "UNDERFILL"); // Close solenoid; report short fill rather than silently claiming completion.
      } // End closure checks.
    } // End dispensing checks.
    if (ch.state == SETTLING && now - ch.changed >= SETTLE_MS) { // Finish counting trailing water.
      if (ch.ml >= ch.target && !strcmp(ch.issue, "UNDERFILL")) ch.issue = "NONE"; // Clear short-fill flag if trailing flow reached target.
      ch.state = DONE; report(c); // Publish final measured volume and issue.
    } // End settling.
  } // End channel service.
  if (now - lastReport >= REPORT_MS) { lastReport = now; report(0); report(1); } // Send periodic telemetry.
} // End main loop.
