# NetLab — demonstration script

A 10-minute walkthrough that covers all five modules. Rehearse it once on the machine you
will actually present from.

**Before you start**

- Run `python -m pytest tests/ -q` once and leave the "126 passed" on screen if you want to
  open with it.
- Decide whether you have internet. If not, set the DNS tab's resolver to **Offline stub**
  before you begin, and skip the HTTP tab.
- Have Wireshark installed and associated with `.pcap`.

---

## 1. Packet Journey — 3 minutes (Modules 1–5)

1. Leave the defaults (HTTP to example.com). Press **Send**.
   Talk over the animation: the bar grows a header at every layer on the way down, crosses
   the wire, and is stripped back on the way up.
2. Click **Total Length** in the field table. The hex dump highlights those exact two bytes.
   Say: *every field on screen knows which bits it occupies — the three panels are one
   picture, not three separate views.*
3. Click a byte in the hex dump. The field table jumps to the field that owns it.
4. Drag **Bit error rate** up two notches. Press **Send**.
   The frame dies at the Data Link layer — the FCS caught it. Point at the red bytes.
5. Now tick **Corrupt inside a router** and press **Send** again.
   Now it gets past the FCS and dies at Network or Transport instead.

   **This is the best 30 seconds of the demo.** Explain: Ethernet's FCS is per-hop. A router
   rebuilds the frame and signs a fresh FCS, so corruption inside a router is waved through
   by the next hop — and only the end-to-end IP and TCP checksums can still catch it. That
   is the end-to-end argument, on screen.
6. Press **Export .pcap**, save it, open it in Wireshark.
   Wireshark dissects Ethernet → IPv4 → TCP → HTTP with no checksum warnings.
   Say: *this is independent proof the headers are correct, not just a drawing of a packet.*

## 2. Link Lab — 2 minutes (Module 5.1–5.2, CO4)

1. **Hamming** tab. Data `1011` gives the (7,4) codeword `0110011`.
2. Click bit 5 in the **received** row. The syndrome panel recomputes: three parity checks,
   two fail, syndrome = 101 binary = 5 decimal — *the syndrome read as a number is the
   position of the bad bit.* It is corrected automatically.
3. Click a second bit. The verdict turns red: a single-error-correcting code mis-corrects a
   double error. Say that this is a limitation of the code, not of the program.
4. **ARQ Protocols** tab. Leave Go-Back-N with frame 2 lost. Point at the timeline: frame 2
   is lost, frame 3 arrives but is **discarded** because the receiver wants them in order,
   and both are resent.
5. Switch the protocol to **Selective Repeat**. Only frame 2 is resent.
   The comparison panel on the right shows all three side by side on the same losses —
   7 / 8 / 7 transmissions. That table is the entire lesson in one line.

## 3. Application Lab — 2 minutes (Module 2, CO2)

1. **DNS** tab. Press **Send query**.
   Show the three panels: the parsed answer, the socket calls (`socket`, `sendto`,
   `recvfrom`, `close`), and the raw bytes of both query and response.
   Say: *no resolver library — the query was built label by label from the wire format and
   sent over a real UDP socket.* Point out `c0 0c` in the response: a compression pointer.
2. **Socket Chat** tab. Start server, connect client, send a message.
   The logs show the real API sequence: `socket` → `bind` → `listen` → `accept` → `recv`.
3. Switch transport to **UDP**, restart, set **drop** to 0.5, send four or five messages.
   Some simply never arrive and nothing retransmits. Say: *that is the whole difference
   between TCP and UDP, and it is happening over real sockets, not a simulation.*

## 4. Network Lab — 2 minutes (Module 4, CO3)

1. **Subnetting** tab. `192.168.1.0/24` into 4. Point at the binary panel at the bottom:
   the two borrowed bits are in their own column. Say: *any website gives you 62 hosts;
   what matters is which bits were borrowed to get there.*
2. **VLSM** tab. Show the four departments allocated largest-first, and that each block
   starts on a boundary matching its own size.
3. **Routing** tab. Press **Step** repeatedly through Dijkstra — one router is settled per
   step and the working panel shows the path so far.
4. Press **Break R4–R6** and step through. RIP's estimates climb 2, 4, 6, 8… Explain
   count-to-infinity: neither router can see that the other's cheap route runs back through
   itself. Then tick **split horizon** and press it again — the loop is gone in two rounds.

## 5. Physical Lab — 1 minute (Module 5.3–5.4)

1. **Line Coding** tab. All seven schemes share one time axis.
   Choose the preset **Long run of zeros**. Point at AMI going flat and B8ZS/HDB3 inserting
   deliberate polarity violations (the red marks) to keep the receiver's clock alive.
2. **PCM** tab. Drop the sampling rate below twice the signal frequency. The verdict turns
   red and explains the aliasing.
3. **Data Rate Limits** tab. Move the SNR slider: Shannon's curve rises, the Nyquist line
   stays flat. Say: *Nyquist alone says you can go as fast as you like by adding levels —
   Shannon is what stops that.*

---

## Questions you should expect

**"Is this actually networking, or just an animation?"**
Both, and the app is explicit about which is which. The DNS and HTTP tabs use real sockets —
the socket-call log is live. The encapsulation is real byte construction, provable by opening
the exported `.pcap` in Wireshark. Bit errors and routing convergence are simulated, because
corrupting a live NIC needs raw sockets and admin rights.

**"Why does your CRC not match the one in my notes?"**
There are two implementations, deliberately. The textbook long division (what the exam wants)
is on the CRC tab. The Ethernet FCS uses IEEE CRC-32, which is reflected with an initial
value and a final XOR — that is what Wireshark validates against, and it matches the standard
check value `CRC32("123456789") = 0xCBF43926`.

**"Why 62 hosts and not 64?"**
The network address and the broadcast address are not usable. `/31` and `/32` are the
exceptions — RFC 3021 point-to-point links and host routes — and the app handles both.

**"What happens if the college wifi blocks this?"**
The DNS tab has a built-in stub resolver on loopback. Real sockets, real wire format, local
answers. The chat tab is loopback-only anyway.
