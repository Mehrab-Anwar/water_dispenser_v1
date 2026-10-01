# Complete runtime code walkthrough — version 1

Read README.md first for installation and bench commands. This document explains **every nonblank source line** of the five runtime files. Line numbers match the delivered files. Blank lines only separate sections and execute no operation. Development tests are explained in README.md and are not runtime modules.

## Overall flow

The Pi keeps one customer order. The Mega keeps two channel states. Python commands express customer/operator intent; channel telemetry expresses what the firmware measured. No payment approval means no START command. Once an approved order ends, any measured water causes a full-price completion under your chosen policy; zero delivery requests a reversal. Unknown delivery/payment is locked for operator review.

The Mega's loop runs repeatedly. It reads a small serial batch, snapshots pulse counters, checks each channel, and reports measurements. It does not use blocking delay calls. The 100 ms opening delay and five-second closing wait are represented by timestamps and states so the other channel can keep working.

## Syntax you will encounter

- `#` in Python and `//` in C++ introduce explanatory comments; the computer ignores them.
- `=` assigns a value; `==` compares two values. `!=` means not equal.
- Python indentation defines blocks. C++ `{` and `}` define blocks.
- Python `self` refers to this controller/device object. `self.state` is its current transaction state.
- C++ `uint8_t` holds a small unsigned value; `uint32_t` holds a 32-bit unsigned counter/time. `const` means a setting is not modified. `volatile` marks counters that interrupts modify.
- C++ arrays use `[0]` for left and `[1]` for right. Python lists use the same indexing convention.
- `return` exits a function immediately. `continue` skips to the next loop iteration. `raise` reports an error to the calling Python code.
- `if/elif/else` or `if/else if/else` chooses one branch based on conditions.
- `now - previous >= interval` asks whether enough elapsed time passed. Unsigned C++ subtraction allows normal timer wraparound.
- An interrupt calls a short counter function when the flowmeter produces an electrical edge, even if the main loop is doing something else.
- `noInterrupts()` briefly protects a 32-bit read on the Mega's 8-bit processor. `interrupts()` restores interrupt handling.
- A Python f-string such as `f"START,{c},{target}"` places variable values into the outgoing text.
- Integer money is cents internally. Formatting converts 350 cents to the text `3.50` for Qibixx.
- A few source lines contain multiple small statements separated by semicolons; their explanation describes the complete sequence on that line.

## State meanings

| Mega state | Meaning |
|---|---|
| IDLE | No cycle initialized |
| OPENING | Solenoid commanded open; waiting 100 ms before ball power |
| FILLING | Both valves commanded open |
| CLOSING | Ball power removed at 90%; solenoid remains open |
| SETTLING | Both commanded closed; counting trailing water for one second |
| PAUSED | Both commanded closed; target/counter retained |
| DONE | Final result available; inspect volume and issue |

| Pi state | Meaning |
|---|---|
| IDLE | Ready to begin a customer order |
| INITIALIZING | Waiting for Qibixx reader initialization |
| WAIT_TAP | Reader enabled; waiting for card credit/session |
| SELECT | Order selection allowed |
| WAIT_APPROVAL | Price requested; water remains closed |
| READY | Matching card approval or explicit bench payment accepted |
| DISPENSING | At least one jar START was requested |
| STOPPING | Waiting for final stopped-channel measurements |
| CANCELLING | Pending request cancellation is awaiting reader response |
| WAIT_END | End/reversal sent; waiting for reader idle |
| THANK_YOU | Result displayed for ten seconds |
| UNCONFIRMED | Evidence uncertain; operator must resolve before restart |

The mock devices are deliberately simple. They test Pi state transitions, not real payments or hydraulics. The host C++ harness executes the actual firmware separately using simulated pins and timing.

## `arduino/water_vending/config.h`

Read the following source and match each line to the explanation table below.

```cpp
#pragma once // Include these settings only once.
const uint8_t FLOW_PIN[2] = {2, 3}; // Left and right interrupt inputs.
const uint8_t SOL_PIN[2] = {8, 10}; // Left and right solenoid driver inputs.
const uint8_t BALL_PIN[2] = {9, 11}; // Left and right ball-valve driver inputs.
const bool ACTIVE_HIGH = true; // Confirm driver polarity before connecting water.
const float PULSES_PER_LITRE[2] = {330.0f, 330.0f}; // Starting calibration from F=5.5Q; measure each sensor.
const uint32_t BALL_CLOSE_MS = 5000; // Conservative starting closing time; tune on the real valve.
const uint32_t OPEN_DELAY_MS = 100; // Open solenoid this long before powering ball valve.
const uint32_t SETTLE_MS = 1000; // Count trailing water after closing solenoid.
const uint32_t MAX_RUN_MS = 120000; // Bound each channel's entire cycle including pauses.
const uint32_t HOST_TIMEOUT_MS = 3000; // Close valves if Pi heartbeat stops.
const uint32_t NO_FLOW_MS = 8000; // Allow opening time, then stop if no pulses arrive.
const uint32_t REPORT_MS = 250; // Report four times per second.
const uint32_t MAX_TARGET_ML = 20000; // Allow either configured jar size but reject excessive targets.
```

| Source line | Explanation |
|---:|---|
| 1 | Include these settings only once. |
| 2 | Left and right interrupt inputs. |
| 3 | Left and right solenoid driver inputs. |
| 4 | Left and right ball-valve driver inputs. |
| 5 | Confirm driver polarity before connecting water. |
| 6 | Starting calibration from F=5.5Q; measure each sensor. |
| 7 | Conservative starting closing time; tune on the real valve. |
| 8 | Open solenoid this long before powering ball valve. |
| 9 | Count trailing water after closing solenoid. |
| 10 | Bound each channel's entire cycle including pauses. |
| 11 | Close valves if Pi heartbeat stops. |
| 12 | Allow opening time, then stop if no pulses arrive. |
| 13 | Report four times per second. |
| 14 | Allow either configured jar size but reject excessive targets. |

## `arduino/water_vending/water_vending.ino`

Read the following source and match each line to the explanation table below.

```cpp
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
```

| Source line | Explanation |
|---:|---|
| 1 | Use Arduino pins, timing, interrupts, and serial. |
| 2 | Convert validated decimal commands. |
| 3 | Split and compare command words. |
| 4 | Load installer settings. |
| 5 | Counters changed by interrupts. |
| 6 | Previous accepted pulse times. |
| 7 | Count one channel's flow pulses. |
| 8 | Read the microsecond clock. |
| 9 | Reject very closely spaced electrical glitches. |
| 10 | Remember this accepted pulse. |
| 11 | Add one measured pulse. |
| 12 | End glitch check. |
| 13 | End pulse handler. |
| 14 | Interrupt wrapper for the left sensor. |
| 15 | Interrupt wrapper for the right sensor. |
| 16 | Simple channel states. |
| 17 | Printable state names. |
| 18 | Keep each channel's cycle information together. |
| 19 | Current channel state. |
| 20 | Volume and timing fields. |
| 21 | Most recent reason for an abnormal stop. |
| 22 | End channel definition. |
| 23 | Start both channels with zeroed fields. |
| 24 | Fixed-size command buffer. |
| 25 | Number of buffered characters. |
| 26 | Discard an entire oversized command. |
| 27 | Heartbeat and report clocks. |
| 28 | Translate open/closed into driver polarity. |
| 29 | Set the valve driver output. |
| 30 | End valve helper. |
| 31 | Read the interrupt counter atomically on an 8-bit AVR. |
| 32 | Prevent a pulse interrupt during this read. |
| 33 | Copy all four bytes consistently. |
| 34 | Re-enable pulse interrupts. |
| 35 | Return the stable copy. |
| 36 | End atomic read. |
| 37 | Report one channel to the Pi. |
| 38 | Start channel record. |
| 39 | Include current state. |
| 40 | Include delivered millilitres. |
| 41 | Include requested millilitres. |
| 42 | Finish with issue code and newline. |
| 43 | End report. |
| 44 | Stop water and enter a trailing-flow interval. |
| 45 | Immediately shut the solenoid. |
| 46 | Remove power so the auto-return ball valve closes. |
| 47 | Keep measuring trailing flow before reporting completion. |
| 48 | Start settling timer. |
| 49 | Preserve why the channel stopped. |
| 50 | End stop helper. |
| 51 | Validate an unsigned decimal field. |
| 52 | Reject missing and excessively long numbers. |
| 53 | Reject signs and trailing junk. |
| 54 | Convert the already validated digits. |
| 55 | Accept the value. |
| 56 | End numeric validation. |
| 57 | Process one complete serial line. |
| 58 | Reject empty fields instead of letting strtok hide them. |
| 59 | Extract command name. |
| 60 | Extract optional channel. |
| 61 | Extract optional target. |
| 62 | Detect excess fields. |
| 63 | Ignore an empty line. |
| 64 | Accept heartbeat. |
| 65 | Report both channels. |
| 66 | Stop any unfinished cycles. |
| 67 | Close active or paused channels. |
| 68 | Confirm the stop command. |
| 69 | End global stop. |
| 70 | Hold parsed channel and volume. |
| 71 | Validate channel and field count. |
| 72 | Refer to the requested channel. |
| 73 | Begin one new fill. |
| 74 | Validate volume. |
| 75 | Never reset an active cycle. |
| 76 | Clear this channel's counter safely. |
| 77 | Initialize cycle values. |
| 78 | Initialize all cycle clocks. |
| 79 | Open solenoid first. |
| 80 | Start heartbeat allowance. |
| 81 | Pause a dispensing channel. |
| 82 | Shut both valve commands. |
| 83 | Retain target and pulse counter while paused. |
| 84 | Continue an existing fill. |
| 85 | Wait for auto-return valve to close before reopening. |
| 86 | Do not reopen a jar that already reached its target. |
| 87 | Restart opening with preserved volume. |
| 88 | Refuse unsupported command/state combinations. |
| 89 | Confirm accepted command. |
| 90 | Immediately publish its resulting state. |
| 91 | End command processor. |
| 92 | Configure the Mega after reset. |
| 93 | Initialize both channels. |
| 94 | Set closed output latches before changing pin direction. |
| 95 | Enable driver outputs. |
| 96 | Enable flow sensor inputs; confirm sensor electrical compatibility. |
| 97 | Initialize printable channel state. |
| 98 | End channel initialization. |
| 99 | Count left sensor edges. |
| 100 | Count right sensor edges. |
| 101 | Start serial and announce protocol version. |
| 102 | End startup. |
| 103 | Run frequently without blocking delays. |
| 104 | Limit serial work per pass so valve checks cannot starve. |
| 105 | Read a bounded batch of incoming bytes. |
| 106 | Get next byte. |
| 107 | Ignore carriage returns. |
| 108 | Process only complete lines. |
| 109 | Add a C-string terminator. |
| 110 | Never execute truncated commands. |
| 111 | Reset input buffer. |
| 112 | Store a valid byte. |
| 113 | Discard until newline if too long. |
| 114 | End serial batch. |
| 115 | Read time once for this control pass. |
| 116 | Service each channel independently. |
| 117 | Access this channel's fields. |
| 118 | Snapshot total pulses. |
| 119 | Convert cumulative pulses to rounded millilitres. |
| 120 | Remember most recent flow activity. |
| 121 | Identify unfinished controllable states. |
| 122 | Shut down on missing Pi heartbeat. |
| 123 | Bound even a paused or stalled fill. |
| 124 | Wait briefly after solenoid opening. |
| 125 | Power ball valve open and begin normal filling. |
| 126 | End opening step. |
| 127 | Check all water-moving states. |
| 128 | Shut solenoid at requested measured volume. |
| 129 | Stop a stalled sensor or water supply. |
| 130 | Apply initial fixed 90-percent rule. |
| 131 | Begin gentle ball-valve closure. |
| 132 | Wait rated maximum closing time. |
| 133 | Close solenoid; report short fill rather than silently claiming completion. |
| 134 | End closure checks. |
| 135 | End dispensing checks. |
| 136 | Finish counting trailing water. |
| 137 | Clear short-fill flag if trailing flow reached target. |
| 138 | Publish final measured volume and issue. |
| 139 | End settling. |
| 140 | End channel service. |
| 141 | Send periodic telemetry. |
| 142 | End main loop. |

## `pi/config.py`

Read the following source and match each line to the explanation table below.

```python
PRICES = {3: 150, 5: 200}  # Store prices as integer cents to avoid floating-point money errors.
PRODUCTS = {(3,): 1, (5,): 2, (3, 3): 3, (3, 5): 4, (5, 5): 5}  # Map whole baskets to proposed MDB product IDs.
ML = {3: 11356, 5: 18927}  # Rounded millilitres for three and five US gallons.
PAYMENT_SECONDS = 90  # Nayax's currently configured vend-result deadline.
STOP_MARGIN_SECONDS = 10  # Stop before the deadline to allow valve settling and payment reporting.
THANK_YOU_SECONDS = 10  # Hold the completed-order state before returning to idle.
```

| Source line | Explanation |
|---:|---|
| 1 | Store prices as integer cents to avoid floating-point money errors. |
| 2 | Map whole baskets to proposed MDB product IDs. |
| 3 | Rounded millilitres for three and five US gallons. |
| 4 | Nayax's currently configured vend-result deadline. |
| 5 | Stop before the deadline to allow valve settling and payment reporting. |
| 6 | Hold the completed-order state before returning to idle. |

## `pi/controller.py`

Read the following source and match each line to the explanation table below.

```python
import argparse  # Parse terminal startup options.
import select  # Check terminal input without blocking water and payment events.
import sys  # Read standard input and report startup errors.
import time  # Use a monotonic clock for elapsed time.
import uuid  # Create a reference for each bench transaction.
from decimal import Decimal, InvalidOperation  # Parse money without binary floating-point rounding.
import config  # Load prices, volumes, and time limits.

class SerialPort:  # Wrap one real USB serial device.
    def __init__(self, path):  # Open a caller-selected stable device path.
        import serial  # Require pyserial only for real hardware.
        self.port = serial.Serial(path, 115200, timeout=0, write_timeout=1, exclusive=True)  # Use nonblocking reads and bounded writes.
        self.buffer = b""  # Retain incomplete incoming lines.
    def send(self, line):  # Send one ASCII command.
        self.port.write((line + "\n").encode("ascii"))  # Terminate the command with newline.
    def read(self):  # Return all currently available complete lines.
        self.buffer += self.port.read(self.port.in_waiting)  # Collect bytes without waiting.
        if len(self.buffer) > 16384:  # Bound malformed input memory use.
            raise RuntimeError("Serial input overflow")  # Refuse a corrupted connection.
        parts = self.buffer.split(b"\n")  # Separate complete messages.
        self.buffer = parts.pop()  # Keep the last incomplete fragment.
        return [p.decode("ascii").strip() for p in parts if p.strip()]  # Decode complete nonempty messages.
    def close(self):  # Release the serial device.
        self.port.close()  # Close its file descriptor.

class Controller:  # Coordinate one order and two independent fill channels.
    def __init__(self, mega, mdb, bench=False, clock=time.monotonic):  # Accept real or simulated connections.
        self.mega, self.mdb, self.bench, self.clock = mega, mdb, bench, clock  # Save dependencies.
        self.state = "IDLE"  # Start with no customer transaction.
        self.mode = None  # No payment method selected yet.
        self.volumes = [0, 0]  # No jars assigned to either outlet.
        self.sent = [False, False]  # Track start requests to prevent duplicate fills.
        self.acknowledged = [False, False]  # Ignore old channel telemetry until the new start is acknowledged.
        self.channels = [None, None]  # Require channel status before allowing an order.
        self.total = 0  # Requested amount in cents.
        self.deadline = None  # No active approved-payment countdown yet.
        self.request_deadline = None  # Bound waiting for vend approval.
        self.credit = 0  # Simulated cash credit in cents.
        self.ending = False  # No end command has been sent yet.
        self.reference = None  # No order reference yet.
        self.last_ping = -100  # Send a heartbeat on the first tick.
        self.last_mega = self.clock()  # Track whether telemetry is still arriving.
        self.show_at = 0  # Rate-limit console progress output.
        self.ready_at = 0  # Hold terminal thank-you state until this time.
        self.mega.send("STATUS")  # Ask for current channel state without opening valves.
    def command(self, text):  # Interpret one operator command.
        words = text.lower().split()  # Split whitespace-delimited input.
        if not words: return  # Ignore blank input.
        verb = words[0]  # Read requested operation.
        if verb == "help":  # Show the deliberately small command set.
            print("begin card|bench|cash-test; order LEFT RIGHT (0,3,5); pay; credit CENTS; tap; start left|right|both; pause left|right|both; resume left|right|both; cancel; status; quit")  # Explain command syntax.
        elif verb == "status":  # Show transaction and controller status.
            print(self.reference, self.state, self.mode, self.total, self.channels)  # Display current memory state.
            self.mega.send("STATUS")  # Request fresh hardware telemetry.
            if self.mdb: self.mdb.send("D,STATUS")  # Request reader status if connected.
        elif verb == "begin" and len(words) == 2:  # Begin payment-method selection.
            if self.state != "IDLE": raise ValueError("Finish or cancel the current order first")  # Prevent overlapping orders.
            if any(c is None or c[0] not in ("IDLE", "DONE") for c in self.channels): raise ValueError("Mega is not ready; check status")  # Reject unknown or active channels.
            mode = words[1]  # Read chosen method.
            if mode not in ("card", "bench", "cash-test"): raise ValueError("Use card, bench, or cash-test")  # Refuse unknown methods.
            if mode != "card" and not self.bench: raise ValueError("Payment bypass needs --bench")  # Never accidentally enable free real-water operation.
            if mode == "card" and not self.mdb: raise ValueError("No MDB connection")  # Require a card reader connection.
            self.mode = mode  # Store the selected method.
            self.volumes, self.sent = [0, 0], [False, False]  # Clear previous jar assignments and requests.
            self.acknowledged = [False, False]  # Require fresh start acknowledgements for this order.
            self.credit, self.total, self.ending = 0, 0, False  # Reset credit and payment completion state.
            self.deadline = self.request_deadline = None  # Clear previous timing limits.
            self.reference = uuid.uuid4().hex[:12]  # Generate a transaction support reference.
            self.state = "INITIALIZING" if mode == "card" else "SELECT"  # Card reader initializes before selection.
            if mode == "card": self.mdb.send("D,0"); self.mdb.send("D,1")  # Restart authorize-first master once for this session.
            print("Order", self.reference, "Partial delivery is billed fully; contact operator for resolution.")  # State the agreed bench policy.
        elif verb == "order" and len(words) == 3:  # Assign purchased jars directly to left and right.
            if self.state != "SELECT": raise ValueError("Wait for card credit, or begin bench/cash-test")  # Require the correct selection state.
            volumes = [int(words[1]), int(words[2])]  # Read each outlet's gallon selection.
            if any(v not in (0, 3, 5) for v in volumes) or not any(volumes): raise ValueError("Each outlet needs 0, 3, or 5 gallons; at least one jar")  # Validate complete order before storing it.
            self.volumes = volumes  # Save the order only after validation.
            self.total = sum(config.PRICES[v] for v in volumes if v)  # Calculate total cents.
            print("Order total", f"{self.total / 100:.2f}", "Use pay to request approval.")  # Display the basket amount.
        elif verb == "credit" and len(words) == 2:  # Simulate an accepted cash amount.
            if self.mode != "cash-test" or self.state != "SELECT": raise ValueError("credit is only simulated cash before payment")  # Do not invent real cash acceptance.
            value = int(words[1])  # Parse integer cents.
            if value <= 0: raise ValueError("Credit must be positive")  # Reject invalid cash amounts.
            self.credit += value  # Accumulate simulated accepted money.
            print("SIMULATED cash credit:", self.credit, "cents")  # Clearly identify simulated cash.
        elif verb == "pay" and len(words) == 1:  # Approve or request payment for the basket.
            if self.state != "SELECT" or not self.total: raise ValueError("Select an order first")  # Require a valid priced order.
            if self.mode == "card":  # Use the documented Qibixx cashless-master API.
                product = config.PRODUCTS[tuple(sorted(v for v in self.volumes if v))]  # Select whole-basket product ID.
                self.mdb.send(f"D,REQ,{self.total // 100}.{self.total % 100:02d},{product}")  # Send decimal currency amount and basket ID.
                self.state = "WAIT_APPROVAL"  # Keep valves closed pending approval.
                self.request_deadline = self.clock() + 30  # Bound bench approval waiting time.
            else:  # Bench modes do not use real payment hardware.
                if self.mode == "cash-test" and self.credit != self.total: raise ValueError("Cash-test requires exact credit; change is not implemented")  # Avoid silently discarding excess money.
                self.state = "READY"  # Permit dispensing after simulated payment.
                print("BENCH payment accepted; no real payment made")  # Avoid misleading money claims.
        elif verb == "tap" and len(words) == 1 and hasattr(self.mdb, "tap"):  # Supply a card event in simulation only.
            self.mdb.tap()  # Let simulated reader emit credit.
        elif verb in ("start", "pause", "resume") and len(words) == 2:  # Control one or both selected outlets.
            if self.state not in ("READY", "DISPENSING"): raise ValueError("Payment not ready or order is ending")  # Gate every dispensing command.
            if words[1] not in ("left", "right", "both"): raise ValueError("Use left, right, or both")  # Validate outlet name.
            selected = [0, 1] if words[1] == "both" else [0 if words[1] == "left" else 1]  # Map names to numeric channel IDs.
            for c in selected:  # Process selected outlets independently.
                if not self.volumes[c]: continue  # Skip an outlet with no purchased jar.
                if verb == "start":  # Start this purchased jar once.
                    if self.sent[c]: raise ValueError("This jar was already started")  # Prevent restarting purchased volume.
                    self.sent[c] = True  # Latch before sending to avoid duplicate requests.
                    self.channels[c] = ("STARTING", 0, config.ML[self.volumes[c]], "NONE")  # Replace stale previous-order completion.
                    self.mega.send(f"START,{c},{config.ML[self.volumes[c]]}")  # Send target millilitres to Mega.
                    self.state = "DISPENSING"  # Mark at least one requested fill.
                else:  # Pause or resume only a jar already requested.
                    if not self.sent[c]: raise ValueError("Start the jar first")  # Avoid affecting an old channel cycle.
                    self.mega.send(f"{verb.upper()},{c}")  # Ask firmware to validate and perform the transition.
        elif verb == "cancel" and len(words) == 1:  # End an incomplete order.
            self.cancel()  # Apply payment-state-specific cancellation.
        else: raise ValueError("Unknown command; type help")  # Reject malformed operator input.
    def cancel(self):  # Cancel without guessing whether approval happened.
        if self.state in ("READY", "DISPENSING", "STOPPING"):  # Stop a paid or simulated-paid fill.
            self.state = "STOPPING"  # Wait for final trailing-flow reports.
            self.mega.send("STOP")  # Shut active valves on Mega.
        elif self.state == "WAIT_APPROVAL":  # Approval may still be in flight.
            self.mdb.send("D,REQ,-1")  # Cancel pending vend request.
            self.state = "CANCELLING"  # Wait for reader state rather than silently abandoning it.
        elif self.state not in ("IDLE", "THANK_YOU", "UNCONFIRMED"):  # Close a session with no approved vend.
            if self.mode == "card": self.mdb.send("D,READER,0"); self.mdb.send("D,0")  # Disable unused reader session.
            self.state = "IDLE"  # Return to idle without a billed dispense.
    def mega_line(self, line):  # Handle one firmware message.
        self.last_mega = self.clock()  # Update telemetry freshness.
        parts = line.split(",")  # Split ASCII fields.
        if parts[0] == "READY":  # Detect an unexpected Mega reboot.
            if self.state in ("READY", "DISPENSING", "STOPPING"):  # An approved order lost its controller state.
                self.mega.send("STOP"); self.state = "UNCONFIRMED"  # Stop and require operator handling rather than assuming volumes.
                print("MEGA RESET: delivery/payment needs operator review", self.reference)  # Keep this material uncertainty visible.
        elif parts[:2] == ["ACK", "START"] and len(parts) == 3:  # Confirm a newly accepted start.
            c = int(parts[2])  # Read acknowledged channel ID.
            if c in (0, 1) and self.sent[c]: self.acknowledged[c] = True  # Unlock telemetry for that purchased jar.
        elif parts[0] == "CH" and len(parts) == 6:  # Decode channel telemetry.
            c, ml, target = int(parts[1]), int(parts[3]), int(parts[4])  # Parse numeric telemetry fields.
            if c not in (0, 1) or ml < 0 or target < 0: raise ValueError("Invalid channel report")  # Reject invalid measurements.
            if self.sent[c] and not self.acknowledged[c]: return  # Discard previous-cycle reports before new START acknowledgement.
            self.channels[c] = (parts[2], ml, target, parts[5])  # Store latest state, volume, target, and issue.
        elif parts[0] == "ERR":  # Surface refused firmware commands.
            print("MEGA refused command:", line)  # Explain bench failures immediately.
            if self.state in ("READY", "DISPENSING"): self.cancel()  # End the order instead of leaving a start request unresolved.
    def mdb_line(self, line):  # Handle documented Qibixx cashless-master messages.
        print("MDB:", line)  # Display raw replies for hardware verification.
        p = line.split(",")  # Split command response fields.
        if p[:2] == ["d", "ERR"]:  # Detect reader command errors.
            if self.state != "IDLE": self.state = "UNCONFIRMED"; self.mega.send("STOP")  # Do not claim a known payment outcome after protocol failure.
            return  # Stop interpreting this error line.
        if p[:2] != ["d", "STATUS"] or len(p) < 3: return  # Ignore unrelated MDB traffic.
        status = p[2]  # Read cashless status name.
        if status == "INIT" and self.state == "INITIALIZING":  # Reader setup is ready for enable command.
            self.mdb.send("D,READER,1")  # Enable the reader after initialization.
            self.state = "WAIT_TAP"  # Await idle then customer credit event.
        elif status == "IDLE" and self.state == "WAIT_TAP":  # Reader is enabled.
            print("Tap card now; in simulation type tap")  # Prompt preauthorization.
        elif status == "CREDIT" and self.state == "WAIT_TAP":  # Reader opened an authorization-first session.
            self.state = "SELECT"  # Permit customer basket selection.
        elif status == "RESULT" and len(p) >= 4 and self.state in ("WAIT_APPROVAL", "CANCELLING"):  # Process approval or denial.
            if p[3] == "1":  # Reader approved a vend amount.
                amount = Decimal(p[4]) if len(p) > 4 else Decimal(-1)  # Require the documented approved amount.
                if not amount.is_finite() or amount * 100 != self.total:  # Require agreement with requested price.
                    self.mdb.send("D,END,-1"); self.state = "WAIT_END"; self.ready_at = self.clock() + 5  # Revert unexpected approval and wait for reader idle.
                    return  # Do not accept mismatched money.
                cancelled = self.state == "CANCELLING"  # Remember cancellation race with approval.
                self.deadline = self.clock() + config.PAYMENT_SECONDS  # Start conservative local vend-result countdown.
                self.state = "READY"  # Allow dispensing only after matching approval.
                if cancelled: self.cancel()  # A late approval must still be closed as a cancelled order.
            elif p[3] == "-1":  # Reader denied the request.
                self.mdb.send("D,REQ,-1"); self.state = "CANCELLING"  # Request cancellation and wait for reader idle.
        elif status == "IDLE" and self.state == "CANCELLING":  # Pending request/session cancellation finished.
            self.state = "IDLE"  # Permit a new order.
        elif status == "IDLE" and self.state == "WAIT_END":  # Reader returned idle after end command.
            self.state = "THANK_YOU"; self.ready_at = self.clock() + config.THANK_YOU_SECONDS  # Hold completed terminal state for ten seconds.
            print("Reader returned idle; final settlement is verified in Nayax, not inferred from this response.")  # Avoid claiming bank confirmation.
        elif status in ("RESET", "INIT", "IDLE") and self.state in ("READY", "DISPENSING", "STOPPING"):  # Detect an approved session ending unexpectedly.
            self.mega.send("STOP"); self.state = "UNCONFIRMED"  # Close water and require operator review.
            print("Payment session ended unexpectedly", self.reference)  # Show uncertain outcome.
    def finish(self):  # Report basket delivery outcome and finalize payment once.
        if self.ending: return  # Never send duplicate end commands.
        delivered = [self.channels[c][1] if self.sent[c] else 0 for c in range(2)]  # Use measured volumes only from this order's starts.
        complete = all(not v or (self.sent[c] and delivered[c] >= config.ML[v] and self.channels[c][3] == "NONE") for c, v in enumerate(self.volumes))  # Require both purchased jars and no firmware issue.
        outcome = "COMPLETE" if complete else ("PARTIAL" if any(delivered) else "FAILED")  # Distinguish partial delivery from zero delivery.
        print("ORDER", self.reference, outcome, "delivered mL", delivered, "issues", [x[3] if x else "UNKNOWN" for x in self.channels])  # Print bench transaction summary without adding persistent logging yet.
        if outcome == "PARTIAL": print("Full approved price retained. Contact operator with reference", self.reference)  # Apply user's partial-delivery policy.
        self.ending = True  # Latch finalization.
        if self.mode == "card":  # Finalize or revert the approved card basket.
            self.mdb.send("D,END" if any(delivered) else "D,END,-1")  # Charge fully for any measured delivery; revert zero delivery.
            self.state = "WAIT_END"; self.ready_at = self.clock() + 5  # Wait briefly for terminal return to idle.
        else:  # Simulated payment has no real refund or charge.
            self.state = "THANK_YOU"; self.ready_at = self.clock() + config.THANK_YOU_SECONDS  # Hold terminal result before idle.
    def tick(self):  # Service connections and timeouts regardless of terminal input.
        now = self.clock()  # Read monotonic time.
        if now - self.last_ping >= 1: self.mega.send("PING"); self.last_ping = now  # Keep Mega heartbeat alive.
        for line in self.mega.read(): self.mega_line(line)  # Process all available firmware replies.
        if self.mdb:  # Read card events when a reader connection exists.
            for line in self.mdb.read(): self.mdb_line(line)  # Process replies without blocking input or water control.
        if self.state in ("READY", "DISPENSING", "STOPPING") and now - self.last_mega > 3:  # Detect loss of dispensing telemetry.
            self.mega.send("STOP"); self.state = "UNCONFIRMED"  # Avoid finalizing from stale delivered-volume evidence.
            print("MEGA link lost; payment/delivery need operator review", self.reference)  # Make uncertainty explicit.
        if self.state == "WAIT_APPROVAL" and now >= self.request_deadline: self.cancel()  # Cancel a stalled approval request.
        if self.deadline and self.state in ("READY", "DISPENSING") and now >= self.deadline - config.STOP_MARGIN_SECONDS:  # Leave time to end before Nayax deadline.
            print("Payment deadline approaching; stopping order")  # Explain automatic stop.
            self.cancel()  # Stop dispensing and count trailing water.
        stopped = all(not self.sent[c] or self.channels[c][0] == "DONE" for c in range(2))  # Require final measurements for started channels.
        purchased_finished = all(not v or (self.sent[c] and self.channels[c][0] == "DONE") for c, v in enumerate(self.volumes))  # Include purchased but unstarted jars.
        if (self.state == "STOPPING" and stopped) or (self.state == "DISPENSING" and purchased_finished): self.finish()  # Finalize only after final channel reports.
        if self.state == "WAIT_END" and now >= self.ready_at:  # Detect missing terminal completion response.
            self.state = "UNCONFIRMED"; print("Payment end unconfirmed; check Nayax", self.reference)  # Do not show a successful payment claim.
        if self.state == "THANK_YOU" and now >= self.ready_at: self.state = "IDLE"; print("IDLE")  # Return to idle after ten seconds.
        if self.state in ("DISPENSING", "STOPPING") and now >= self.show_at:  # Limit terminal volume output to once per second.
            print("PROGRESS", self.channels); self.show_at = now + 1  # Show each channel's measured progress.


def main():  # Run the terminal application.
    parser = argparse.ArgumentParser(description="Two-channel water vending bench controller")  # Create command-line parser.
    parser.add_argument("--mega", help="Mega serial path, preferably /dev/serial/by-id/...")  # Select the dispensing USB device.
    parser.add_argument("--mdb", help="Qibixx serial path, preferably /dev/serial/by-id/...")  # Select the payment USB device.
    parser.add_argument("--bench", action="store_true", help="Allow explicit payment bypass and simulated cash")  # Require opt-in for real-water bypass.
    parser.add_argument("--sim", action="store_true", help="Simulate both devices; no real water or payment")  # Allow safe terminal testing without hardware.
    args = parser.parse_args()  # Read supplied options.
    if args.sim:  # Use local device simulations.
        from simulator import MegaSim, MdbSim  # Import simulations only when selected.
        mega, mdb = MegaSim(), MdbSim()  # Create two simulated connections.
    else:  # Open real serial ports.
        if not args.mega: parser.error("--mega is required without --sim")  # Require explicit Mega device selection.
        mega = SerialPort(args.mega)  # Open Mega serial connection, potentially resetting the board.
        try: mdb = SerialPort(args.mdb) if args.mdb else None  # Open optional Qibixx connection.
        except Exception: mega.close(); raise  # Release Mega if payment-port opening fails.
        time.sleep(2)  # Allow the Mega's USB reset to finish before commands.
    controller = Controller(mega, mdb, args.bench or args.sim)  # Create application state.
    print("Type help. No UI; cash hardware and persistent transaction logging are not implemented yet.")  # State this version's scope.
    try:  # Ensure errors and exit shut down commanded water.
        while True:  # Service the operator and both devices repeatedly.
            controller.tick()  # Process progress, payment, and deadlines.
            readable, _, _ = select.select([sys.stdin], [], [], 0.05)  # Wait at most fifty milliseconds for terminal input.
            if readable:  # Read a command only when available.
                line = sys.stdin.readline()  # Read the complete operator line.
                if not line or line.strip() == "quit": break  # Exit on terminal EOF or quit command.
                try: controller.command(line)  # Dispatch the requested operation.
                except (ValueError, InvalidOperation) as error: print("Command rejected:", error)  # Explain invalid bench input without crashing.
    finally:  # Shut valves even when an unexpected exception exits the app.
        mega.send("STOP")  # Request immediate closing.
        if controller.state not in ("IDLE", "THANK_YOU"):  # Handle an unfinished transaction on normal exit.
            try:  # Try to collect final measurements and close the payment session.
                controller.cancel()  # Apply correct cancellation behavior.
                until = time.monotonic() + 2.5  # Allow settling reports without waiting indefinitely.
                while time.monotonic() < until: controller.tick(); time.sleep(0.05)  # Continue heartbeat and event handling during shutdown.
                if controller.state not in ("IDLE", "THANK_YOU"): print("Unresolved payment; check Nayax. Reference:", controller.reference)  # Warn about an unfinished payment rather than guess.
            except Exception as error: print("Shutdown issue:", error, "Check valves and payment")  # Expose failures in the shutdown attempt.
        mega.close()  # Release dispensing serial device.
        if mdb: mdb.close()  # Release payment serial device.
if __name__ == "__main__": main()  # Start only when run as a script.
```

| Source line | Explanation |
|---:|---|
| 1 | Parse terminal startup options. |
| 2 | Check terminal input without blocking water and payment events. |
| 3 | Read standard input and report startup errors. |
| 4 | Use a monotonic clock for elapsed time. |
| 5 | Create a reference for each bench transaction. |
| 6 | Parse money without binary floating-point rounding. |
| 7 | Load prices, volumes, and time limits. |
| 9 | Wrap one real USB serial device. |
| 10 | Open a caller-selected stable device path. |
| 11 | Require pyserial only for real hardware. |
| 12 | Use nonblocking reads and bounded writes. |
| 13 | Retain incomplete incoming lines. |
| 14 | Send one ASCII command. |
| 15 | Terminate the command with newline. |
| 16 | Return all currently available complete lines. |
| 17 | Collect bytes without waiting. |
| 18 | Bound malformed input memory use. |
| 19 | Refuse a corrupted connection. |
| 20 | Separate complete messages. |
| 21 | Keep the last incomplete fragment. |
| 22 | Decode complete nonempty messages. |
| 23 | Release the serial device. |
| 24 | Close its file descriptor. |
| 26 | Coordinate one order and two independent fill channels. |
| 27 | Accept real or simulated connections. |
| 28 | Save dependencies. |
| 29 | Start with no customer transaction. |
| 30 | No payment method selected yet. |
| 31 | No jars assigned to either outlet. |
| 32 | Track start requests to prevent duplicate fills. |
| 33 | Ignore old channel telemetry until the new start is acknowledged. |
| 34 | Require channel status before allowing an order. |
| 35 | Requested amount in cents. |
| 36 | No active approved-payment countdown yet. |
| 37 | Bound waiting for vend approval. |
| 38 | Simulated cash credit in cents. |
| 39 | No end command has been sent yet. |
| 40 | No order reference yet. |
| 41 | Send a heartbeat on the first tick. |
| 42 | Track whether telemetry is still arriving. |
| 43 | Rate-limit console progress output. |
| 44 | Hold terminal thank-you state until this time. |
| 45 | Ask for current channel state without opening valves. |
| 46 | Interpret one operator command. |
| 47 | Split whitespace-delimited input. |
| 48 | Ignore blank input. |
| 49 | Read requested operation. |
| 50 | Show the deliberately small command set. |
| 51 | Explain command syntax. |
| 52 | Show transaction and controller status. |
| 53 | Display current memory state. |
| 54 | Request fresh hardware telemetry. |
| 55 | Request reader status if connected. |
| 56 | Begin payment-method selection. |
| 57 | Prevent overlapping orders. |
| 58 | Reject unknown or active channels. |
| 59 | Read chosen method. |
| 60 | Refuse unknown methods. |
| 61 | Never accidentally enable free real-water operation. |
| 62 | Require a card reader connection. |
| 63 | Store the selected method. |
| 64 | Clear previous jar assignments and requests. |
| 65 | Require fresh start acknowledgements for this order. |
| 66 | Reset credit and payment completion state. |
| 67 | Clear previous timing limits. |
| 68 | Generate a transaction support reference. |
| 69 | Card reader initializes before selection. |
| 70 | Restart authorize-first master once for this session. |
| 71 | State the agreed bench policy. |
| 72 | Assign purchased jars directly to left and right. |
| 73 | Require the correct selection state. |
| 74 | Read each outlet's gallon selection. |
| 75 | Validate complete order before storing it. |
| 76 | Save the order only after validation. |
| 77 | Calculate total cents. |
| 78 | Display the basket amount. |
| 79 | Simulate an accepted cash amount. |
| 80 | Do not invent real cash acceptance. |
| 81 | Parse integer cents. |
| 82 | Reject invalid cash amounts. |
| 83 | Accumulate simulated accepted money. |
| 84 | Clearly identify simulated cash. |
| 85 | Approve or request payment for the basket. |
| 86 | Require a valid priced order. |
| 87 | Use the documented Qibixx cashless-master API. |
| 88 | Select whole-basket product ID. |
| 89 | Send decimal currency amount and basket ID. |
| 90 | Keep valves closed pending approval. |
| 91 | Bound bench approval waiting time. |
| 92 | Bench modes do not use real payment hardware. |
| 93 | Avoid silently discarding excess money. |
| 94 | Permit dispensing after simulated payment. |
| 95 | Avoid misleading money claims. |
| 96 | Supply a card event in simulation only. |
| 97 | Let simulated reader emit credit. |
| 98 | Control one or both selected outlets. |
| 99 | Gate every dispensing command. |
| 100 | Validate outlet name. |
| 101 | Map names to numeric channel IDs. |
| 102 | Process selected outlets independently. |
| 103 | Skip an outlet with no purchased jar. |
| 104 | Start this purchased jar once. |
| 105 | Prevent restarting purchased volume. |
| 106 | Latch before sending to avoid duplicate requests. |
| 107 | Replace stale previous-order completion. |
| 108 | Send target millilitres to Mega. |
| 109 | Mark at least one requested fill. |
| 110 | Pause or resume only a jar already requested. |
| 111 | Avoid affecting an old channel cycle. |
| 112 | Ask firmware to validate and perform the transition. |
| 113 | End an incomplete order. |
| 114 | Apply payment-state-specific cancellation. |
| 115 | Reject malformed operator input. |
| 116 | Cancel without guessing whether approval happened. |
| 117 | Stop a paid or simulated-paid fill. |
| 118 | Wait for final trailing-flow reports. |
| 119 | Shut active valves on Mega. |
| 120 | Approval may still be in flight. |
| 121 | Cancel pending vend request. |
| 122 | Wait for reader state rather than silently abandoning it. |
| 123 | Close a session with no approved vend. |
| 124 | Disable unused reader session. |
| 125 | Return to idle without a billed dispense. |
| 126 | Handle one firmware message. |
| 127 | Update telemetry freshness. |
| 128 | Split ASCII fields. |
| 129 | Detect an unexpected Mega reboot. |
| 130 | An approved order lost its controller state. |
| 131 | Stop and require operator handling rather than assuming volumes. |
| 132 | Keep this material uncertainty visible. |
| 133 | Confirm a newly accepted start. |
| 134 | Read acknowledged channel ID. |
| 135 | Unlock telemetry for that purchased jar. |
| 136 | Decode channel telemetry. |
| 137 | Parse numeric telemetry fields. |
| 138 | Reject invalid measurements. |
| 139 | Discard previous-cycle reports before new START acknowledgement. |
| 140 | Store latest state, volume, target, and issue. |
| 141 | Surface refused firmware commands. |
| 142 | Explain bench failures immediately. |
| 143 | End the order instead of leaving a start request unresolved. |
| 144 | Handle documented Qibixx cashless-master messages. |
| 145 | Display raw replies for hardware verification. |
| 146 | Split command response fields. |
| 147 | Detect reader command errors. |
| 148 | Do not claim a known payment outcome after protocol failure. |
| 149 | Stop interpreting this error line. |
| 150 | Ignore unrelated MDB traffic. |
| 151 | Read cashless status name. |
| 152 | Reader setup is ready for enable command. |
| 153 | Enable the reader after initialization. |
| 154 | Await idle then customer credit event. |
| 155 | Reader is enabled. |
| 156 | Prompt preauthorization. |
| 157 | Reader opened an authorization-first session. |
| 158 | Permit customer basket selection. |
| 159 | Process approval or denial. |
| 160 | Reader approved a vend amount. |
| 161 | Require the documented approved amount. |
| 162 | Require agreement with requested price. |
| 163 | Revert unexpected approval and wait for reader idle. |
| 164 | Do not accept mismatched money. |
| 165 | Remember cancellation race with approval. |
| 166 | Start conservative local vend-result countdown. |
| 167 | Allow dispensing only after matching approval. |
| 168 | A late approval must still be closed as a cancelled order. |
| 169 | Reader denied the request. |
| 170 | Request cancellation and wait for reader idle. |
| 171 | Pending request/session cancellation finished. |
| 172 | Permit a new order. |
| 173 | Reader returned idle after end command. |
| 174 | Hold completed terminal state for ten seconds. |
| 175 | Avoid claiming bank confirmation. |
| 176 | Detect an approved session ending unexpectedly. |
| 177 | Close water and require operator review. |
| 178 | Show uncertain outcome. |
| 179 | Report basket delivery outcome and finalize payment once. |
| 180 | Never send duplicate end commands. |
| 181 | Use measured volumes only from this order's starts. |
| 182 | Require both purchased jars and no firmware issue. |
| 183 | Distinguish partial delivery from zero delivery. |
| 184 | Print bench transaction summary without adding persistent logging yet. |
| 185 | Apply user's partial-delivery policy. |
| 186 | Latch finalization. |
| 187 | Finalize or revert the approved card basket. |
| 188 | Charge fully for any measured delivery; revert zero delivery. |
| 189 | Wait briefly for terminal return to idle. |
| 190 | Simulated payment has no real refund or charge. |
| 191 | Hold terminal result before idle. |
| 192 | Service connections and timeouts regardless of terminal input. |
| 193 | Read monotonic time. |
| 194 | Keep Mega heartbeat alive. |
| 195 | Process all available firmware replies. |
| 196 | Read card events when a reader connection exists. |
| 197 | Process replies without blocking input or water control. |
| 198 | Detect loss of dispensing telemetry. |
| 199 | Avoid finalizing from stale delivered-volume evidence. |
| 200 | Make uncertainty explicit. |
| 201 | Cancel a stalled approval request. |
| 202 | Leave time to end before Nayax deadline. |
| 203 | Explain automatic stop. |
| 204 | Stop dispensing and count trailing water. |
| 205 | Require final measurements for started channels. |
| 206 | Include purchased but unstarted jars. |
| 207 | Finalize only after final channel reports. |
| 208 | Detect missing terminal completion response. |
| 209 | Do not show a successful payment claim. |
| 210 | Return to idle after ten seconds. |
| 211 | Limit terminal volume output to once per second. |
| 212 | Show each channel's measured progress. |
| 215 | Run the terminal application. |
| 216 | Create command-line parser. |
| 217 | Select the dispensing USB device. |
| 218 | Select the payment USB device. |
| 219 | Require opt-in for real-water bypass. |
| 220 | Allow safe terminal testing without hardware. |
| 221 | Read supplied options. |
| 222 | Use local device simulations. |
| 223 | Import simulations only when selected. |
| 224 | Create two simulated connections. |
| 225 | Open real serial ports. |
| 226 | Require explicit Mega device selection. |
| 227 | Open Mega serial connection, potentially resetting the board. |
| 228 | Open optional Qibixx connection. |
| 229 | Release Mega if payment-port opening fails. |
| 230 | Allow the Mega's USB reset to finish before commands. |
| 231 | Create application state. |
| 232 | State this version's scope. |
| 233 | Ensure errors and exit shut down commanded water. |
| 234 | Service the operator and both devices repeatedly. |
| 235 | Process progress, payment, and deadlines. |
| 236 | Wait at most fifty milliseconds for terminal input. |
| 237 | Read a command only when available. |
| 238 | Read the complete operator line. |
| 239 | Exit on terminal EOF or quit command. |
| 240 | Dispatch the requested operation. |
| 241 | Explain invalid bench input without crashing. |
| 242 | Shut valves even when an unexpected exception exits the app. |
| 243 | Request immediate closing. |
| 244 | Handle an unfinished transaction on normal exit. |
| 245 | Try to collect final measurements and close the payment session. |
| 246 | Apply correct cancellation behavior. |
| 247 | Allow settling reports without waiting indefinitely. |
| 248 | Continue heartbeat and event handling during shutdown. |
| 249 | Warn about an unfinished payment rather than guess. |
| 250 | Expose failures in the shutdown attempt. |
| 251 | Release dispensing serial device. |
| 252 | Release payment serial device. |
| 253 | Start only when run as a script. |

## `pi/simulator.py`

Read the following source and match each line to the explanation table below.

```python
import time  # Supply a real monotonic clock for interactive simulation.

class MegaSim:  # Provide lightweight serial-like dispensing behavior.
    def __init__(self, clock=time.monotonic):  # Accept a controllable clock for tests.
        self.clock = clock  # Store the clock function.
        self.last = clock()  # Initialize elapsed-time reference.
        self.channels = [["IDLE", 0, 0, "NONE"], ["IDLE", 0, 0, "NONE"]]  # Initialize two independent channels.
        self.lines = []  # Queue messages for the Pi.
        self.commands = []  # Retain sent commands for assertions.
    def send(self, line):  # Interpret commands from the Pi.
        self.commands.append(line)  # Record the command for tests.
        p = line.split(",")  # Split command fields.
        if p[0] == "PING": self.lines.append("PONG")  # Return heartbeat acknowledgement.
        elif p[0] == "START":  # Begin a requested simulated fill.
            self.channels[int(p[1])] = ["FILLING", 0, int(p[2]), "NONE"]  # Initialize the selected channel.
            self.lines.append(f"ACK,START,{p[1]}")  # Acknowledge before publishing new channel reports.
        elif p[0] == "PAUSE": self.channels[int(p[1])][0] = "PAUSED"  # Pause without losing volume.
        elif p[0] == "RESUME": self.channels[int(p[1])][0] = "FILLING"  # Resume the same measured fill.
        elif p[0] == "STOP":  # Stop only unfinished channels.
            for ch in self.channels:  # Visit both channels.
                if ch[0] not in ("IDLE", "DONE"): ch[0] = "DONE"; ch[3] = "CANCELLED"  # Preserve partial volumes and issue.
    def read(self):  # Advance simulated water and emit telemetry.
        now = self.clock()  # Get current simulation time.
        dt = max(0, now - self.last)  # Measure elapsed interval.
        self.last = now  # Start the next interval here.
        for c, ch in enumerate(self.channels):  # Advance each channel independently.
            if ch[0] == "FILLING":  # Water moves only while running.
                ch[1] = min(ch[2], ch[1] + dt * 650)  # Use approximately 29 seconds per five-gallon fill.
                if ch[1] >= ch[2]: ch[0] = "DONE"  # Finish at the requested measured amount.
            self.lines.append(f"CH,{c},{ch[0]},{int(ch[1])},{ch[2]},{ch[3]}")  # Emit protocol-compatible channel report.
        result, self.lines = self.lines, []  # Drain queued reports once.
        return result  # Return all currently available messages.
    def close(self): pass  # Simulation has no physical serial device to release.

class MdbSim:  # Simulate the documented cashless-master happy path.
    def __init__(self):  # Initialize reader simulation.
        self.lines, self.commands = [], []  # Store pending replies and outgoing command history.
    def send(self, line):  # React to Pi payment commands.
        self.commands.append(line)  # Preserve exact commands for tests.
        if line == "D,1": self.lines.append("d,STATUS,INIT,0")  # Advertise authorization-first initialization.
        elif line == "D,READER,1": self.lines.append("d,STATUS,IDLE")  # Advertise enabled reader.
        elif line.startswith("D,REQ,") and line != "D,REQ,-1":  # Approve a priced vend request.
            amount = line.split(",")[2]  # Read decimal amount.
            self.lines.extend(["d,STATUS,VEND", f"d,STATUS,RESULT,1,{amount}"])  # Emit pending then approved states.
        elif line in ("D,END", "D,END,-1", "D,REQ,-1"): self.lines.append("d,STATUS,IDLE")  # Return idle after ending or cancelling.
    def tap(self): self.lines.append("d,STATUS,CREDIT,4.00,-1")  # Simulate a card starting a four-dollar credit session.
    def read(self):  # Drain queued reader replies.
        result, self.lines = self.lines, []  # Clear the queue after reading.
        return result  # Return all currently available responses.
    def close(self): pass  # No physical device exists in simulation.
```

| Source line | Explanation |
|---:|---|
| 1 | Supply a real monotonic clock for interactive simulation. |
| 3 | Provide lightweight serial-like dispensing behavior. |
| 4 | Accept a controllable clock for tests. |
| 5 | Store the clock function. |
| 6 | Initialize elapsed-time reference. |
| 7 | Initialize two independent channels. |
| 8 | Queue messages for the Pi. |
| 9 | Retain sent commands for assertions. |
| 10 | Interpret commands from the Pi. |
| 11 | Record the command for tests. |
| 12 | Split command fields. |
| 13 | Return heartbeat acknowledgement. |
| 14 | Begin a requested simulated fill. |
| 15 | Initialize the selected channel. |
| 16 | Acknowledge before publishing new channel reports. |
| 17 | Pause without losing volume. |
| 18 | Resume the same measured fill. |
| 19 | Stop only unfinished channels. |
| 20 | Visit both channels. |
| 21 | Preserve partial volumes and issue. |
| 22 | Advance simulated water and emit telemetry. |
| 23 | Get current simulation time. |
| 24 | Measure elapsed interval. |
| 25 | Start the next interval here. |
| 26 | Advance each channel independently. |
| 27 | Water moves only while running. |
| 28 | Use approximately 29 seconds per five-gallon fill. |
| 29 | Finish at the requested measured amount. |
| 30 | Emit protocol-compatible channel report. |
| 31 | Drain queued reports once. |
| 32 | Return all currently available messages. |
| 33 | Simulation has no physical serial device to release. |
| 35 | Simulate the documented cashless-master happy path. |
| 36 | Initialize reader simulation. |
| 37 | Store pending replies and outgoing command history. |
| 38 | React to Pi payment commands. |
| 39 | Preserve exact commands for tests. |
| 40 | Advertise authorization-first initialization. |
| 41 | Advertise enabled reader. |
| 42 | Approve a priced vend request. |
| 43 | Read decimal amount. |
| 44 | Emit pending then approved states. |
| 45 | Return idle after ending or cancelling. |
| 46 | Simulate a card starting a four-dollar credit session. |
| 47 | Drain queued reader replies. |
| 48 | Clear the queue after reading. |
| 49 | Return all currently available responses. |
| 50 | No physical device exists in simulation. |

