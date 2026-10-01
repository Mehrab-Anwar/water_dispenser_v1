# Water vending — terminal bench version 1

This is a NEW two-channel controller, not a patch to the uploaded four-nozzle UI project. The old UI is intentionally not used. Run the Python app in a Raspberry Pi terminal; upload the Arduino sketch to an Arduino Mega 2560. No touchscreen UI or persistent transaction database is included yet.

## What this version does

- Left/right channels, each with a solenoid and a powered-open, power-off auto-return ball valve.
- Three and five US gallon jars; one or two jars; whole-basket card requests.
- Independent or simultaneous starts, independent pause/resume, four firmware reports per second.
- Solenoid opens first; after 100 ms ball-valve power opens; at 90% ball-valve power is removed; solenoid closes at the measured target OR after the configured ball closure period.
- Simple startup-closed outputs, host heartbeat, no-flow timeout, maximum cycle time, bounded serial input, duplicate-start protection.
- Approved card orders: any measured delivery finalizes the FULL basket amount; zero delivery sends failure/reversal. A pause alone does not finalize payment.
- Explicit simulated cash and payment bypass for bench tests. REAL BILL VALIDATOR INTEGRATION IS NOT PRESENT.
- Ten seconds of terminal completion state, then idle. Partial details are printed with a support reference; they are not persistently saved yet.

## Files and reading order

1. `arduino/water_vending/config.h`: wiring and timing settings.
2. `arduino/water_vending/water_vending.ino`: hardware control.
3. `pi/config.py`: prices, basket IDs, volumes, payment timing.
4. `pi/controller.py`: terminal and transaction control.
5. `pi/simulator.py`: optional mock devices.
6. `LINE_BY_LINE.md`: an explanation of every nonblank line of all five runtime files.
7. `PROTOCOL.md`: wire commands and responses.

Every runtime source line has an explanatory comment. Tests are development checks, not additional files that must run on the Pi.

## Pin assignment

| Device signal | Left | Right |
|---|---:|---:|
| Flowmeter pulse input | Mega 2 | Mega 3 |
| Solenoid driver input | Mega 8 | Mega 10 |
| Ball-valve driver input | Mega 9 | Mega 11 |

The Arduino pins drive the MOSFET board INPUTS, not valve coils. Verify the board's active-HIGH polarity and the sensor output voltage/wiring before connecting. Mega flow inputs are 5 V logic; confirm the actual sensor's output type. Do not feed valve supply voltage into these inputs. The firmware assumes NC solenoids and two-wire/power-off auto-return ball valves; a reversing-polarity or three-wire valve requires a different driver/control arrangement.

The Pi has two USB connections: one to Mega and one to Qibixx. MDB payment devices share the MDB bus, not the Mega's flow/valve connections. This package does not replace the existing power-wiring instructions.

## First run without any hardware

On the Raspberry Pi (or another Linux computer) open a terminal in this folder:

```bash
python3 pi/controller.py --sim
```

Enter commands ONE AT A TIME. The app services device replies between commands.

```text
begin card
```

Wait for the tap prompt, then:

```text
tap
order 3 5
pay
```

Wait for `d,STATUS,RESULT,1,3.50`, then:

```text
start both
```

You will see progress approximately once per second. This simulation takes about 29 seconds for five gallons. It does not model the ball valve hydraulics; firmware timing is checked separately by the C++ tests.

To test independent starts, use `start left`, then `start right` a second or more later. For a single right jar use `order 0 5`.

```text
pause right
resume right
status
cancel
quit
```

In real hardware, wait AT LEAST `BALL_CLOSE_MS` after pausing before resume; otherwise firmware returns `ERR,WAIT_CLOSE` and the first version conservatively ends the order. Do not use the simulator's immediate resume to infer physical valve behavior.

## Upload the Arduino sketch

Open `arduino/water_vending/water_vending.ino` in Arduino IDE. Select **Arduino Mega or Mega 2560**, processor **ATmega2560**, and the correct USB port. Verify and upload. `config.h` must remain beside the `.ino` file. No additional Arduino libraries are required.

A real AVR build was not available in the development environment: the supplied firmware was compiled and exercised using a host Arduino stub, not uploaded to a physical Mega. Arduino IDE Verify is part of the first hardware test.

Start with valve power/water disconnected. Verify each driver's output and inactive startup polarity before enabling water. Physical output pulldowns and coil protection are hardware matters; software cannot prevent every boot-time floating-input condition or mechanical stuck valve.

## Install Python dependency and identify serial devices

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r pi/requirements.txt
ls -l /dev/serial/by-id/
```

Use the actual paths shown. Do not assume `/dev/ttyACM0` belongs to a particular device after reboot. If stable IDs are absent, identify devices individually before selecting port paths. Close Arduino Serial Monitor and minicom before running the app. Only this app should own either serial port.

If serial access is denied, add your Pi user to `dialout`, then log out/in:

```bash
sudo usermod -aG dialout "$USER"
```

## Real dispensing with payments bypassed

```bash
python pi/controller.py --mega /dev/serial/by-id/YOUR_MEGA_ID --bench
```

Wait for channel reports, then:

```text
begin bench
order 3 5
pay
start both
```

`--bench` explicitly permits dispensing without real payment. Keep this mode for supervised testing. It is not a customer payment configuration.

## Real card plus real dispensing

```bash
python pi/controller.py --mega /dev/serial/by-id/YOUR_MEGA_ID --mdb /dev/serial/by-id/YOUR_QIBIXX_ID
```

Wait for Mega status, enter `begin card`, wait for the reader prompt, TAP A REAL CARD, then enter `order 3 5`, `pay`, and after approval `start both`. The `tap` terminal command exists only in simulation.

Reader initialization uses `D,0`, `D,1`, waits for INIT, then sends `D,READER,1`. Credit enables selection. `D,REQ,3.50,4` requests approval for the basket. No separate `D,VEND` is sent: Qibixx's published master API uses the `d,STATUS,VEND` reply as the pending-approval state. If your actual firmware differs, capture its responses and adapt the payment module before proceeding.

Prices are decimal currency amounts in the terminal's configured currency. For your Canadian deployment confirm CAD in Nayax; writing `1.50` does not select a currency. Confirm preauthorization covers the maximum four-dollar basket and the proposed basket IDs behave as intended in Nayax reporting.

The 90-second local deadline begins when Pi receives vend approval. At 80 seconds it requests STOP, leaving ten seconds for trailing-flow reports and end processing. The actual terminal deadline may start at a different instant and cannot be extended by Python. Verify its timing on hardware. Pauses do not stop this clock. Simultaneous manifold flow has not been measured.

`D,END` followed by reader idle means the vending protocol returned idle. It is NOT proof of final bank settlement or the exact final amount in the merchant account. Verify those in Nayax during the bench test. Zero-water failure requests reversal; do not promise an instant bank refund.

## Cash simulation only

```bash
python pi/controller.py --sim
```

```text
begin cash-test
order 3 5
credit 350
pay
start both
```

`credit` is integer CENTS and is always explicitly simulated. It does not read the validator. This version requires exact simulated credit; change and bill refunds are not implemented. Identify and test the actual validator before enabling real cash. A non-recycling bill validator may be unable to refund a stacked bill.

## Calibration and the 90% rule

Initial factor: 330 pulses per litre from the previously supplied `F = 5.5 × Q` specification. Test with an independent volume/weight reference and update EACH channel in `config.h`:

`new factor = old factor × displayed volume / independently measured volume`

Use consistent volume units in this ratio. Recompile/upload after changes. This first version has no EEPROM calibration or predictive flow algorithm.

At 90%, removing ball-valve power does NOT guarantee the remaining 10% will be delivered. Flow tapers as the valve closes. At the target the solenoid shuts immediately; if five seconds elapse first, it also shuts and reports UNDERFILL. Tune the fixed threshold/time after observing each jar size. No tolerance band is silently applied: a below-target final volume remains partial. Water hammer reduction and absolute fill accuracy require physical validation.

Pause shuts the solenoid immediately AND removes ball-valve power. This favors stopping water; it is not the gentle normal-completion sequence. During pause the flow counter remains active and trailing flow is included. Resume preserves the cumulative target/count. If the target was reached during pause, resume does not reopen it.

## Faults and limitations

| Code/state | Meaning/action |
|---|---|
| NONE | No firmware issue recorded |
| NO_FLOW | No accepted pulse for eight seconds while dispensing |
| UNDERFILL | Ball closing period ended before measured target |
| HOST_LOST | No Pi heartbeat for three seconds; both outputs commanded closed |
| MAX_TIME | Channel exceeded 120 seconds including pauses |
| CANCELLED | Pi requested STOP; measured amount is retained |
| UNCONFIRMED | Payment or delivery evidence is uncertain; app locks new orders pending operator review |

An unplugged flowmeter resembles absent flow; NO_FLOW cannot diagnose which component failed. `UNCONFIRMED` is intentionally not auto-cleared. Stop the app, inspect valve state and the transaction in Nayax, resolve it with the operator, then restart for a new bench run. This version has no persistent restart recovery. Unknown outcomes are not automatically charged/reversed from stale measurements.

When exiting normally the app tries STOP, final telemetry, and payment completion. A power loss cannot run that shutdown code; firmware heartbeat closes commanded valves when the Pi stops responding, but payment resolution may still require the operator. This is a supervised bench version, not production release firmware.

## Run development checks

```bash
python3 -m unittest discover -s tests -v
g++ -std=c++11 -Wall -Wextra -Werror -I tests/arduino_stub tests/firmware_test.cpp -o /tmp/water-v1-test
/tmp/water-v1-test
```

Tests cover payment gating, all-or-partial completion, zero-delivery reversal, separate starts, paused volume retention, stale completion reports, timeout handling, and unknown delivery after reset. Host firmware checks cover output sequencing, target cutoff, 90% closure, no-flow, heartbeat loss, malformed commands, duplicate START, and trailing-flow completion.

## Deferred work

Real cash integration, persistent SQLite/CSV transaction records, UI integration, restart recovery, detailed hardware failsafes, and physical calibration. This package keeps those out of the first implementation as requested.

## Protocol sources used

- https://docs.qibixx.com/mdb-products/api-cashless-master
- https://docs.qibixx.com/mdb-products/vending-sessions-examples
- https://docs.qibixx.com/mdb-products/mdb-pi-hat-firststeps-using-usb

These document the intended ASCII sequence. This code's real HAT/Nayax path has not been exercised on your connected hardware.
