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
