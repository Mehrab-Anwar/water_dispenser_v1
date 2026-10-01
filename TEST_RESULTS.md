# Validation record

Validation performed in the development container on 2026-09-30 UTC (2026-10-01 in Dhaka).

- Python source compilation: passed.
- Eleven Python controller tests: passed.
- Actual firmware compiled under g++ with `-std=c++11 -Wall -Wextra -Werror`, using the included Arduino host stub: passed.
- Firmware behavior harness: passed.
- Walkthrough coverage: all 459 nonblank runtime source lines have explanations.

Not performed: AVR cross-compilation, Arduino upload, electrical driver tests, physical valve/flowmeter tests, real Qibixx/Nayax transactions, simultaneous hydraulic flow measurement, or real bill-validator integration.

The Python device simulator and firmware host harness are separate checks. The simulator does not establish that the physical 90% closure rule gives an accurate final fill. Follow the README bench sequence and verify real transaction records in Nayax.
