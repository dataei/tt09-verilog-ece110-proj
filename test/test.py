# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge


# ----------------------------
# Helpers: signal access
# ----------------------------

def _has(dut, name: str) -> bool:
    try:
        getattr(dut, name)
        return True
    except Exception:
        return False

def _get_sig(dut, *names):
    """Return the first signal that exists on dut."""
    for n in names:
        if _has(dut, n):
            return getattr(dut, n)
    raise AttributeError(f"Could not find any of signals: {names}")

def _as_uint(val) -> int:
    return int(val.value)

def _get_ui_in(dut):
    # Tiny Tapeout common name in tests: ui_in
    return _get_sig(dut, "ui_in", "ui", "ui_in_i")

def _get_uo_out(dut):
    # Common Tiny Tapeout wrapper output
    return _get_sig(dut, "uo_out", "uo", "uo_out_o")

def _get_uio_out(dut):
    return _get_sig(dut, "uio_out", "uio", "uio_out_o")

def _get_uio_oe(dut):
    # not always present in testbench
    for n in ("uio_oe", "uio_oe_o"):
        if _has(dut, n):
            return getattr(dut, n)
    return None

def _get_reset(dut):
    return _get_sig(dut, "rst_n", "reset_n", "rst")

def _get_enable(dut):
    # some TT wrappers include 'ena'
    for n in ("ena", "enable", "en"):
        if _has(dut, n):
            return getattr(dut, n)
    return None

def _membrane(dut) -> int:
    return _as_uint(_get_uo_out(dut))

def _spike_bit(dut) -> int:
    uio = _get_uio_out(dut)
    width = len(uio.value)
    # Your info.yaml says uio[7] is spike.
    # If uio_out is 8-bit, take bit 7. If it's 1-bit, take bit 0.
    if width >= 8:
        return (int(uio.value) >> 7) & 1
    return int(uio.value) & 1


# ----------------------------
# Clock API compatibility
# ----------------------------

def _make_clock(dut, period_ns=1):
    """
    cocotb Clock API differs across versions:
      - newer: Clock(sig, period, unit="ns")
      - older: Clock(sig, period, units="ns")
    """
    try:
        return Clock(dut.clk, period_ns, unit="ns")
    except TypeError:
        return Clock(dut.clk, period_ns, units="ns")


async def _init(dut, period_ns=1):
    """Start clock and put DUT in a known state."""
    clock = _make_clock(dut, period_ns)
    cocotb.start_soon(clock.start())

    rst = _get_reset(dut)
    ena = _get_enable(dut)
    if ena is not None:
        ena.value = 1

    ui = _get_ui_in(dut)
    ui.value = 0

    # Reset
    rst.value = 0
    await ClockCycles(dut.clk, 5)
    rst.value = 1
    await ClockCycles(dut.clk, 2)

async def _drive_current(dut, value: int, cycles: int):
    ui = _get_ui_in(dut)
    ui.value = value & 0xFF
    await ClockCycles(dut.clk, cycles)

async def _collect(dut, cycles: int):
    """Collect (membrane, spike) for N cycles."""
    mem = []
    spk = []
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        mem.append(_membrane(dut))
        spk.append(_spike_bit(dut))
    return mem, spk


# ----------------------------
# Core tests
# ----------------------------

@cocotb.test()
async def test_reset_clears_state(dut):
    """
    After reset, outputs should settle to a deterministic baseline quickly.
    We don't assume baseline is exactly 0, but it should be stable with zero input.
    """
    await _init(dut)

    await _drive_current(dut, 0, 5)
    mem, spk = await _collect(dut, 20)

    assert sum(spk) == 0, "Spike asserted with zero input right after reset"

    tail = mem[len(mem)//2 :]
    assert max(tail) - min(tail) <= 2, f"Membrane not stable after reset under 0 input: {tail}"


@cocotb.test()
async def test_no_input_no_spike(dut):
    """With ui_in = 0 for an extended time, neuron should not spike."""
    await _init(dut)

    await _drive_current(dut, 0, 10)
    _, spk = await _collect(dut, 200)
    assert sum(spk) == 0, "Unexpected spike(s) with zero input"


@cocotb.test()
async def test_integrates_up_with_constant_input(dut):
    """
    With a moderate constant input, membrane should tend to increase (at least initially)
    unless leak dominates heavily. We check for a positive trend early on.
    """
    await _init(dut)

    await _drive_current(dut, 20, 5)
    mem, spk = await _collect(dut, 60)

    if 1 in spk:
        mem = mem[:spk.index(1)]

    if len(mem) >= 10:
        start_avg = sum(mem[:5]) / 5
        mid_avg   = sum(mem[5:10]) / 5
        assert mid_avg >= start_avg, f"Membrane didn't integrate upward early: start={start_avg}, mid={mid_avg}"


@cocotb.test()
async def test_leak_down_when_input_removed(dut):
    """Drive neuron up with current, then set input to 0 and verify it leaks down."""
    await _init(dut)

    await _drive_current(dut, 30, 5)
    mem1, _ = await _collect(dut, 50)

    await _drive_current(dut, 0, 1)
    mem2, spk2 = await _collect(dut, 80)

    charged_level = max(mem1) if mem1 else _membrane(dut)
    after_level = sum(mem2[-10:]) / 10

    assert after_level <= charged_level + 2, f"Membrane didn't leak down after removing input: charged_peak={charged_level}, after_avg={after_level}"
    assert sum(spk2) == 0, "Unexpected spike(s) after input removed (ui_in=0)"


@cocotb.test()
async def test_spike_and_reset_behavior(dut):
    """
    Force at least one spike, then verify spike corresponds to a drop compared to recent pre-spike peak.
    Handles designs where reset happens in same cycle as spike.
    """
    await _init(dut)

    await _drive_current(dut, 255, 2)
    mem, spk = await _collect(dut, 250)

    assert 1 in spk, "Did not observe any spike under maximum input"

    i = spk.index(1)

    pre_lo = max(0, i - 10)
    pre_hi = i
    pre_window = mem[pre_lo:pre_hi] if pre_hi > pre_lo else [mem[i]]
    pre_peak = max(pre_window)

    post_lo = i
    post_hi = min(len(mem), i + 5)
    post_window = mem[post_lo:post_hi]
    post_min = min(post_window)

    assert post_min <= pre_peak, (
        f"Spike did not cause a drop vs recent peak: "
        f"pre_peak={pre_peak}, post_min(first5)={post_min}, i={i}, "
        f"pre_window={pre_window}, post_window={post_window}"
    )


@cocotb.test()
async def test_spike_is_pulse_not_stuck_high(dut):
    """Spike should not remain high for many consecutive cycles."""
    await _init(dut)

    await _drive_current(dut, 255, 2)
    _, spk = await _collect(dut, 200)

    max_run = 0
    run = 0
    for b in spk:
        if b == 1:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0

    assert max_run <= 2, f"Spike stayed high too long (max consecutive={max_run})"


@cocotb.test()
async def test_periodic_spiking_under_strong_drive(dut):
    """Under strong constant input, expect multiple spikes."""
    await _init(dut)

    await _drive_current(dut, 200, 1)
    _, spk = await _collect(dut, 400)

    assert sum(spk) >= 2, f"Expected repeated spikes under strong drive, saw {sum(spk)}"


@cocotb.test()
async def test_random_stimulus_invariants(dut):
    """Randomly vary input and check invariants."""
    import random

    await _init(dut)

    ui = _get_ui_in(dut)

    for _ in range(300):
        ui.value = random.randrange(0, 256)
        await RisingEdge(dut.clk)

        m = _membrane(dut)
        s = _spike_bit(dut)

        assert 0 <= m <= 255, f"Membrane out of 8-bit range: {m}"
        assert s in (0, 1), f"Spike not 0/1: {s}"


@cocotb.test()
async def test_step_response_charge_then_decay(dut):
    """Step input up then down; membrane should rise then decay."""
    await _init(dut)

    await _drive_current(dut, 0, 5)
    base, _ = await _collect(dut, 20)
    base_avg = sum(base[-10:]) / 10

    await _drive_current(dut, 40, 1)
    up, spk_up = await _collect(dut, 40)
    if 1 in spk_up:
        up = up[:spk_up.index(1)]
    if len(up) >= 10:
        up_avg = sum(up[-10:]) / 10
        assert up_avg >= base_avg, f"Membrane didn't increase on step up: base={base_avg}, up={up_avg}"

    await _drive_current(dut, 0, 1)
    down, spk_down = await _collect(dut, 60)
    down_avg = sum(down[-10:]) / 10

    assert sum(spk_down) == 0, "Unexpected spike(s) during decay with zero input"
    assert down_avg <= (sum(up[-10:]) / 10 if len(up) >= 10 else max(up, default=base_avg)) + 2, \
        f"Membrane didn't decay after step down: down_avg={down_avg}"