/* Minimal Arduino core stub so the Mega firmware can be compiled and
 * exercised on a PC. Only what water_dispenser_mega.ino actually uses. */
#ifndef ARDUINO_H_STUB
#define ARDUINO_H_STUB

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <deque>

#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT 0
#define INPUT_PULLUP 2
#define FALLING 2
#define RISING 3
#define CHANGE 4

typedef uint8_t byte;

class __FlashStringHelper;
#define F(str) (reinterpret_cast<const __FlashStringHelper *>(str))

/* ---- virtual machine state -------------------------------------- */
namespace sim {
extern uint32_t now_us;                       /* virtual clock          */
extern int pin_mode[70];
extern int pin_state[70];
extern std::deque<char> serial_in;            /* bytes the Pi "sent"    */
extern std::vector<std::string> serial_out;   /* complete lines emitted */
extern std::string serial_partial;
extern uint8_t eeprom[4096];
void emit(const std::string &s);
}  // namespace sim

inline uint32_t millis() { return sim::now_us / 1000UL; }
inline uint32_t micros() { return sim::now_us; }
inline void delay(uint32_t ms) { sim::now_us += ms * 1000UL; }
inline void pinMode(uint8_t p, uint8_t m) { sim::pin_mode[p] = m; }
inline void digitalWrite(uint8_t p, uint8_t v) { sim::pin_state[p] = v; }
inline int digitalRead(uint8_t p) { return sim::pin_state[p]; }
inline uint8_t digitalPinToInterrupt(uint8_t p) { return p; }
inline void attachInterrupt(uint8_t, void (*)(), int) {}
inline void noInterrupts() {}
inline void interrupts() {}

/* ---- Serial ------------------------------------------------------ */
class SerialStub {
 public:
  void begin(long) {}
  int available() { return (int)sim::serial_in.size(); }
  int read() {
    if (sim::serial_in.empty()) return -1;
    char c = sim::serial_in.front();
    sim::serial_in.pop_front();
    return (int)(unsigned char)c;
  }
  void print(const char *s) { sim::emit(s); }
  void print(const __FlashStringHelper *s) { sim::emit(reinterpret_cast<const char *>(s)); }
  void print(char c) { sim::emit(std::string(1, c)); }
  void print(int v) { sim::emit(std::to_string(v)); }
  void print(unsigned int v) { sim::emit(std::to_string(v)); }
  void print(long v) { sim::emit(std::to_string(v)); }
  void print(unsigned long v) { sim::emit(std::to_string(v)); }
  void print(float v, int digits = 2) {
    char buf[32];
    snprintf(buf, sizeof(buf), "%.*f", digits, v);
    sim::emit(buf);
  }
  void println() { sim::emit("\n"); }
  template <typename T> void println(T v) { print(v); println(); }
  void println(float v, int digits) { print(v, digits); println(); }
};
extern SerialStub Serial;

#endif  /* ARDUINO_H_STUB */
