#!/usr/bin/env python3
"""
Unit tests for pulser3.dds -- DDS bus encoding (DDS_BUS_CONTRACT.md v0.3). No hardware:

    python -m pulser3.test_dds     # (also discoverable by pytest)
"""
from . import dds as D
from . import wiremap as W

# Rows that drove board 8 through 50/100/150/200 MHz + RF-off on hardware
# (VHDL_files/XEM7305_Pulser_2026_09_07/bp_proto/bp_proto.vhd ROM, 2026-11-13).
HW_ROWS = [
    (50e6,  True,  "0ccccccccccd0000b40001"),
    (100e6, True,  "19999999999a0000b40001"),
    (150e6, True,  "2666666666660000b40001"),
    (200e6, True,  "3333333333330000b40001"),
    (200e6, False, "3333333333330000b40000"),
]


def test_rows_match_hardware_verified_bytes():
    for f, rf, hexrow in HW_ROWS:
        assert D.Row(f, 0.0, 0xB40, rf).to_bytes().hex() == hexrow, (f, rf)


def test_ftw_exact_frequencies():
    # counter-verified tunings (2026-11-08): 300 MHz and +1 / +0.1 / +0.01 Hz
    assert D.ftw_from_hz(300e6) == 0x4CCCCCCCCCCD
    assert D.ftw_from_hz(300_000_001) == 0x4CCCCCD11850
    assert D.ftw_from_hz(300_000_000.1) == 0x4CCCCCCD3AC0
    assert D.ftw_from_hz(300_000_000.01) == 0x4CCCCCCCD7CC
    for f in (1e6, 12.345678e6, 123.456789e6, 399.999999e6):
        assert abs(D.Row(f).exact_hz - f) <= 1e9 / 2**49 + 1e-9    # <= half an LSB


def test_phase_and_fields():
    r = D.Row(0.0, 180.0, 0x123, True).to_int()
    assert (r >> 24) & 0xFFFF == 0x8000             # POW16 = half a turn
    assert (r >> 26) & 0x3FFF == 0x2000             # the 14 bits the AD9912 gets
    assert (r >> 12) & 0xFFF == 0x123
    assert r & 0xFF == 1 and (r >> 8) & 0xF == 0
    assert D.pow16_from_deg(360.0) == 0 and D.pow16_from_deg(-90.0) == 0xC000
    assert D.OFF.to_bytes() == bytes(11)


def test_frames():
    assert D.reset() == bytes([0x1F, 0x02])
    assert D.step(5) == bytes([0x05, 0x03])
    assert D.write_reg(8, 0x040B, 0x55) == bytes([0x08, 0x04, 0x04, 0x0B, 0x55])
    f = D.write_rows(3, 0x0102, [D.Row(50e6, 0, 0xB40, True), D.OFF])
    assert f[:4] == bytes([0x03, 0x01, 0x01, 0x02]) and len(f) == 4 + 2 * 11
    assert f[4:15].hex() == HW_ROWS[0][2]
    assert D.set_dac_fsc(1, 0x200) == [bytes([1, 4, 0x04, 0x0C, 0x02]), bytes([1, 4, 0x04, 0x0B, 0x00])]


def test_pack_roundtrip_and_padding():
    cases = [
        [D.reset()],                                            # 4 bytes -> even gap
        [D.write_rows(1, 0, [D.OFF])],                          # 2+15 = 17 -> odd gap
        [D.write_rows(1, 0, [D.OFF] * 3), D.step()],            # 2+37 + 4 = 43 -> odd gap 5
        [D.write_rows(2, 0, [D.OFF] * 5), D.reset(), D.step(2)],
        [D.write_reg(4, 0x10, 0xD0)] * 3,
    ]
    for frames in cases:
        for block in (16, 64, 1024):
            s = D.pack(frames, block)
            assert len(s) % block == 0
            back = D.unpack(s)
            # the original frames come first, then at most one NOP filler
            assert back[:len(frames)] == frames, (frames, block)
            assert all(f[1] == D.CMD_NOP for f in back[len(frames):])
            assert len(back) - len(frames) <= 1


def test_odd_gap_smaller_than_a_nop_record():
    # content whose gap to the block is 1 or 3 bytes must grow by a block, not break
    for nrows in range(0, 12):
        frames = [D.write_rows(1, 0, [D.OFF] * (nrows + 1))]
        s = D.pack(frames, 16)
        assert D.unpack(s)[0] == frames[0]


def test_program_board_chunks_and_limits():
    rows = [D.Row(0.5e6 * (i + 1), 0, 0x100, True) for i in range(600)]
    fr = D.program_board(7, rows, start=10, chunk=256)
    assert len(fr) == 3
    assert [int.from_bytes(f[2:4], "big") for f in fr] == [10, 266, 522]
    assert sum((len(f) - 4) // 11 for f in fr) == 600
    try:
        D.program_board(7, rows, start=D.N_ROWS - 10)
        assert False, "should reject a table past 8192 rows"
    except D.DDSError:
        pass


def test_vga_cal_board8_points():
    cal = D.VgaCal()
    # board 8 @ 50 MHz (2026-11-07): 0xA11 -> -5.01 dBm, 0xC6F -> +5.00, 0xECD -> +15.2
    assert abs(cal.code(-5.0) - 0xA11) <= 8
    assert abs(cal.code(5.0) - 0xC6F) <= 8
    assert abs(cal.code(15.0) - 0xECD) <= 16
    assert D.row_dbm(50e6, 0.0).vga == 0xB40


def test_errors():
    for bad in (lambda: D.Row(600e6).to_int(), lambda: D.Row(1e6, 0, 0x1000).to_int(),
                lambda: D.reset(32), lambda: D.write_rows(1, 0, []),
                lambda: D.write_reg(1, 0x2000, 0), lambda: D.pack([b"\x01"]),
                lambda: D.VgaCal().code(30.0)):
        try:
            bad()
            assert False, "expected DDSError"
        except D.DDSError:
            pass


def test_wiremap_constants():
    assert W.DDS_PIPE == 0x81 and (W.TRIG_DDS_STEP_BIT, W.TRIG_DDS_RESET_BIT, W.TRIG_DDS_CLEAR_BIT) == (6, 7, 8)
    assert (W.DDS_ADVANCE_CHANNEL, W.DDS_RESET_CHANNEL) == (18, 19)


if __name__ == "__main__":
    import sys
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"test_dds: {len(tests)} tests passed")
    sys.exit(0)
