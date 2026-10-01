# Protocol v1

All messages are ASCII, newline terminated, 115200 baud. Mega channel 0 is LEFT, 1 is RIGHT. Volume fields are integer millilitres. This protocol differs from the uploaded four-nozzle project's protocol.

| Pi command | Meaning |
|---|---|
| `PING` | Heartbeat; Mega replies `PONG` |
| `STATUS` | Report both channels |
| `START,0,11356` | Start left jar; target 11,356 mL |
| `START,1,18927` | Start right jar; target 18,927 mL |
| `PAUSE,0` | Shut left valve commands; retain volume |
| `RESUME,0` | Resume after ball closing time |
| `STOP` | Shut all unfinished channel valve commands |

`start both` in the Pi app sends two START lines back-to-back. They are independent cycles, not an atomic dual-channel start. A failure during either request causes the first version to stop the order.

| Mega message | Meaning |
|---|---|
| `READY,1` | Mega booted; protocol version 1 |
| `ACK,START,0` | Left START accepted |
| `ACK,PAUSE,0` | Left pause accepted |
| `ACK,RESUME,0` | Left resume accepted |
| `ACK,STOP` | All active outputs commanded closed |
| `CH,0,FILLING,1234,11356,NONE` | Channel,state,delivered mL,target mL,issue |
| `CH,0,DONE,11360,11356,NONE` | Final channel result, after settling |
| `ERR,FORMAT` | Invalid fields or channel |
| `ERR,TARGET` | Invalid target |
| `ERR,BUSY` | Channel already running |
| `ERR,STATE` | Unsupported command or wrong state |
| `ERR,WAIT_CLOSE` | Resume attempted before ball closure wait ended |
| `ERR,OVERFLOW` | Command too long; entire line discarded |

DONE is a terminal channel state, not proof that its target was delivered. Pi checks delivered millilitres and issue code. Four CH reports per second per channel are also sent while paused; trailing water remains counted. Closed output commands are not feedback from physical valve-position sensors.

## Payment sequence

Initialize once at `begin card`: `D,0`, `D,1`; wait INIT; `D,READER,1`; wait IDLE and then CREDIT after card tap. Select basket; `D,REQ,<decimal amount>,<basket ID>`; wait `d,STATUS,RESULT,1,<matching amount>`; only then allow start.

`d,STATUS,VEND` indicates pending approval, not permission to open water. `d,STATUS,RESULT,-1` denies vending. Approved order with some measured delivery ends with `D,END` under the agreed full-charge policy. Approved order with no measured delivery ends with `D,END,-1`. A still-pending request is cancelled with `D,REQ,-1`.

No money and no raw payment card data are stored persistently in v1. Future transaction records will distinguish dispensing status from payment confirmation/settlement.
