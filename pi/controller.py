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
