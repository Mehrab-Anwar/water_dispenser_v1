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
