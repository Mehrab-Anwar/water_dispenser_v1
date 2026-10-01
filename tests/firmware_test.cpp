#include "Arduino.h"
#include <cassert>
namespace sim {
uint32_t now_us = 0;
int pin_mode[70] = {}, pin_state[70] = {};
std::deque<char> serial_in;
std::vector<std::string> serial_out;
std::string serial_partial;
uint8_t eeprom[4096] = {};
void emit(const std::string& s) {
  for(char c : s) {
    if(c == '\n') { serial_out.push_back(serial_partial); serial_partial.clear(); }
    else serial_partial += c;
  }
}
}
SerialStub Serial;
#include "../arduino/water_vending/water_vending.ino"
void send(const std::string& s) {
  for(char c : s + "\n") sim::serial_in.push_back(c);
  while(!sim::serial_in.empty()) loop();
}
void advance(unsigned ms, bool heartbeat=true) {
  for(unsigned i=0; i<ms; i+=10) {
    sim::now_us += 10000;
    if(heartbeat && i % 500 == 0) send("PING");
    loop();
  }
}
void reset() {
  sim::now_us=0;
  for(int c=0;c<2;c++) { pulses[c]=0; lastUs[c]=0; channels[c]={}; }
  used=0; overflow=false; lastHost=0; lastReport=0;
  sim::serial_in.clear(); setup();
}
int main() {
  reset();
  assert(sim::pin_state[8]==LOW && sim::pin_state[9]==LOW);
  send("START,0,1000");
  assert(sim::pin_state[8]==HIGH && sim::pin_state[9]==LOW);
  advance(100); assert(sim::pin_state[9]==HIGH);
  pulses[0]=297; loop();
  assert(channels[0].state==CLOSING && sim::pin_state[9]==LOW && sim::pin_state[8]==HIGH);
  pulses[0]=330; loop();
  assert(channels[0].state==SETTLING && sim::pin_state[8]==LOW);
  advance(1100); assert(channels[0].state==DONE && channels[0].ml==1000);
  reset(); send("START,0,1000"); send("START,1,2000"); advance(100);
  send("PAUSE,0"); assert(channels[0].state==PAUSED && sim::pin_state[8]==LOW);
  assert(sim::pin_state[10]==HIGH);
  send("RESUME,0"); assert(channels[0].state==PAUSED);
  pulses[0]=100; loop(); advance(5000); send("RESUME,0");
  assert(channels[0].state==OPENING && channels[0].ml==303);
  reset(); send("START,0,1000"); advance(8100);
  assert(channels[0].state==SETTLING && !strcmp(channels[0].issue,"NO_FLOW"));
  reset(); send("START,0,1000"); advance(3100,false);
  assert(sim::pin_state[8]==LOW && !strcmp(channels[0].issue,"HOST_LOST"));
  reset(); send("START,0,1000"); advance(100); pulses[0]=297; loop(); advance(5100);
  assert(!strcmp(channels[0].issue,"UNDERFILL") && sim::pin_state[8]==LOW);
  reset(); send("START,0,-10"); assert(channels[0].state==IDLE);
  send("START,0,1000junk"); assert(channels[0].state==IDLE);
  send(std::string(100,'X')+",START,0,1000"); assert(channels[0].state==IDLE);
  send("START,0,1000"); send("START,0,2000"); assert(channels[0].target==1000);
  send("STOP"); assert(sim::pin_state[8]==LOW);
  printf("Firmware behavior checks passed (host stub; not AVR hardware).\n");
}
