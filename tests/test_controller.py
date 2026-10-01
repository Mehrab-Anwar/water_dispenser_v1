import contextlib
import io
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pi'))
from controller import Controller
from simulator import MegaSim, MdbSim

class Clock:
    now = 0
    def __call__(self): return self.now

class Tests(unittest.TestCase):
    def setUp(self):
        self.capture = contextlib.redirect_stdout(io.StringIO())
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)
        self.clock = Clock()
        self.mega = MegaSim(self.clock)
        self.mdb = MdbSim()
        self.c = Controller(self.mega, self.mdb, True, self.clock)
        self.c.tick()
    def advance(self, seconds):
        for _ in range(seconds):
            self.clock.now += 1
            self.c.tick()
    def card(self):
        self.c.command('begin card'); self.c.tick(); self.c.tick()
        self.c.command('tap'); self.c.tick()
        self.c.command('order 3 5'); self.c.command('pay'); self.c.tick()
        self.assertEqual(self.c.state, 'READY')
        self.assertIn('D,REQ,3.50,4', self.mdb.commands)
    def test_card_complete_and_ten_second_idle(self):
        self.card(); self.c.command('start both'); self.advance(32)
        self.assertIn('D,END', self.mdb.commands)
        self.advance(12); self.assertEqual(self.c.state, 'IDLE')
    def test_partial_full_charge(self):
        self.card(); self.c.command('start left'); self.advance(5)
        self.c.command('cancel'); self.c.tick()
        self.assertIn('D,END', self.mdb.commands)
        self.assertNotIn('D,END,-1', self.mdb.commands)
    def test_zero_delivery_reverts(self):
        self.card(); self.c.command('cancel'); self.c.tick()
        self.assertIn('D,END,-1', self.mdb.commands)
    def test_pause_resume_and_duplicate_start(self):
        self.c.command('begin bench'); self.c.command('order 5 0'); self.c.command('pay')
        self.c.command('start left'); self.advance(5)
        with self.assertRaises(ValueError): self.c.command('start left')
        self.c.command('pause left'); self.advance(1)
        volume = self.c.channels[0][1]; self.advance(5)
        self.assertEqual(self.c.channels[0][1], volume)
        self.c.command('resume left'); self.advance(30)
        self.assertEqual(self.c.state, 'THANK_YOU')
    def test_deadline_cancels_unstarted_order(self):
        self.card(); self.advance(81)
        self.assertIn('D,END,-1', self.mdb.commands)
    def test_cash_exact_only(self):
        self.c.command('begin cash-test'); self.c.command('order 3 0')
        self.c.command('credit 200')
        with self.assertRaises(ValueError): self.c.command('pay')
    def test_no_start_without_payment(self):
        self.c.command('begin bench'); self.c.command('order 3 5')
        with self.assertRaises(ValueError): self.c.command('start both')
    def test_bad_approval_reverted(self):
        self.card(); self.c.state = 'WAIT_APPROVAL'
        self.c.mdb_line('d,STATUS,RESULT,1,2.00')
        self.assertEqual(self.c.state, 'WAIT_END')
        self.assertEqual(self.mdb.commands[-1], 'D,END,-1')
    def test_reset_keeps_uncertainty(self):
        self.card(); self.c.command('start left'); self.advance(2)
        self.c.mega_line('READY,1')
        self.assertEqual(self.c.state, 'UNCONFIRMED')
        self.assertEqual(self.mega.commands[-1], 'STOP')
    def test_old_done_report_cannot_complete_new_fill(self):
        self.card(); self.c.command('start left')
        self.c.mega_line('CH,0,DONE,18927,18927,NONE')
        self.assertEqual(self.c.channels[0][0], 'STARTING')
    def test_two_fills_started_separately(self):
        self.card(); self.c.command('start left'); self.advance(2)
        self.c.command('start right'); self.advance(32)
        self.assertIn('D,END', self.mdb.commands)

if __name__ == '__main__':
    with contextlib.redirect_stdout(io.StringIO()): unittest.main()
