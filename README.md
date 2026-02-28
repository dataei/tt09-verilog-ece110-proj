<img width="2600" height="900" alt="Screenshot 2026-02-27 183141" src="https://github.com/user-attachments/assets/f2f413f4-f374-45c9-85ac-d8767f7d278f" />
## How it works

This project implements a simple leaky integrate-and-fire (LIF) neuron in Verilog. The idea is to take an input “current” value each clock cycle, integrate it into a membrane state variable, and then generate a spike when the membrane crosses a threshold. After spiking, the membrane is reset so it can start integrating again.

I structured the design as two modules:

tt_um_lif: the Tiny Tapeout top module. This is the wrapper that connects the Tiny Tapeout pins to my neuron logic. The ui[7:0] inputs are treated as an 8-bit input current, and the uo[7:0] outputs show the current membrane state (so I can see it change over time). I use uio[7] as a 1-bit spike output.

lif: the actual neuron logic. This module does the integrate-leak-threshold behavior and outputs the updated membrane value plus the spike signal.

On each rising edge of the clock, the neuron updates its membrane state using two effects:

Integrate: add the input current into the membrane value (so sustained input pushes the membrane higher).

Leak: apply a decay so the membrane slowly drops if the input stops (so it doesn’t just grow forever).

After updating, the logic checks a threshold. If the membrane value reaches or exceeds that threshold, the module outputs a spike (a 1 on the spike bit) and resets the membrane back down (either to zero or a reset value, depending on how it’s parameterized). If the threshold isn’t reached, the spike stays low and the membrane just keeps evolving normally.

I kept the I/O simple on purpose: the membrane state is directly visible on uo[7:0], and the spike is a single bit so it’s easy to test. This makes it straightforward to drive different input patterns on ui[7:0] and watch the membrane charge up, leak down, and spike when it crosses the threshold.

## How to test

I test this project in two main ways: a fast, “does it behave logically” simulation, and a more realistic end-to-end run that matches how Tiny Tapeout expects the module to be wired.

1) Basic simulation (quick sanity checks)

The first thing I do is drive ui[7:0] with simple input patterns and watch the membrane output (uo[7:0]) and spike bit (uio[7]) over time. The goal here is to confirm the neuron’s core behavior:

Integration: with a steady nonzero input current, the membrane value should rise over successive clock cycles.

Leak: if I set the input back to zero, the membrane should decay downward instead of holding constant forever.

Threshold + spike: if the input is strong enough, the membrane should eventually cross the threshold, produce a spike pulse, and then reset.

I usually run a few small test cases:

Zero input: membrane should stay near baseline (or decay to it) and never spike.

Small constant input: membrane rises slowly and might not spike depending on threshold/leak.

Large constant input: membrane crosses threshold and spikes periodically (because it resets and starts integrating again).

Step input: input turns on and off so I can see both charging and leaking clearly.

2) Cocotb regression tests (the official “does it pass” check)

For the actual project workflow, I use the test/ directory with cocotb. The tests compile my RTL (the wrapper tt_um_lif.v plus lif.v), run a Python-based testbench, and generate:

results.xml (pass/fail report)

tb.vcd (waveform file so I can visually inspect signals)

In CI (GitHub Actions), the test job runs:

cd test

make clean

make
and then checks results.xml to make sure there are no failures. If something breaks, I open the waveform and verify whether the issue is in the neuron logic (integration/leak/threshold) or in the wrapper wiring (inputs/outputs mapped incorrectly).

3) What I look for in the waveform

When I open tb.vcd, I specifically check:

ui[7:0] changes at the intended times (input stimulus is correct)

uo[7:0] responds on clock edges (synchronous update)

uio[7] goes high only when the membrane crosses the threshold

after a spike, the membrane resets as expected (and doesn’t immediately spike again unless the input is still high enough)

This combination of small targeted patterns + a repeatable automated test makes it easy to catch wiring mistakes early and confirm the neuron behavior stays consistent after edits.


