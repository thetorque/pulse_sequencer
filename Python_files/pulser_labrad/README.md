# pulser_labrad -- py3 LabRAD server for the XEM7305 pulser (over scalabrad)

A thin py3 LabRAD **`Pulser`** server that re-exposes the headless `pulser3`
driver over LabRAD, for the modern cross-platform **scalabrad** manager. Keeps
the legacy setting IDs/names so existing clients and the rest of the lab's
LabRAD ecosystem work unchanged; all hardware goes through `pulser3`.

```
scalabrad manager (JVM)  ──LabRAD──►  Pulser server (this, py3)  ──►  pulser3.Driver  ──►  XEM7305
```

This is the **minimal proof-of-stack** server (sequence build / program / run /
stop / status). PMT counting, DDS, and switch manual/auto are added next.

## Files

| file | role |
|---|---|
| `pulser_server.py` | the `Pulser` LabRAD server (run this) |
| `test_client.py` | minimal client: build a TTL sequence, program, run, wait |
| `pmt_client.py` | exercise the PMT counting settings (normal + timetags) |

## Settings

Sequence build/run (proof-of-stack): `New Sequence` (0), `Add TTL Pulse` (5),
`Add TTL Pulses` (6), `Extend Sequence Length` (7), `Program Sequence` (1),
`Start Single` (4), `Start Infinite` (2), `Start Number` (9), `Stop Sequence`
(8), `Wait Sequence Done` (16), `Repeatitions Completed` (17), `Get Channels`
(12).

PMT photon counting (legacy IDs/names, over the pulser3 datapath): `Set Mode`
(21, Normal/Differential), `Set Collection Time` (22), `Get Collection Time`
(23), `Reset FIFO Normal` (24), `Get PMT Counts` (25, `(rate_kc/s, status,
time)`), `Get Collection Mode` (28), `Reset Timetags` (31), `Record Timetags`
(30), `Get Timetags` (32, seconds), `Get TimeTag Resolution` (33). Bring-up
helpers for the on-FPGA synthetic source: `Set PMT Synthetic` (19), `Set PMT
Sim Rate` (20). DDS (90-92) and the second-PMT/readout settings are not ported
(hardware-blocked / unbuilt).

## One-time setup

### 1. Java (scalabrad needs a JVM)
Install a JDK 8+ (11 is fine) and make sure `java -version` works.

### 2. scalabrad manager
Download a release from <https://github.com/labrad/scalabrad/releases>
(`scalabrad-<ver>.tar.gz`), extract it, and run the launcher:

```bash
./bin/labrad --registry file:///path/to/registry?format=delphi --password <PW>
```

- First run creates the registry directory.
- Note the **password** you set -- clients use it too.
- **TLS gotcha:** scalabrad defaults to requiring TLS. For a local, single-host
  setup the simplest path is to disable it (see the scalabrad README for the
  current flag, e.g. `--tls-required false` / `LABRAD_TLS=off`). This is the
  most common first-run snag; if the server/client can't connect, TLS is the
  first thing to check.
- Default port is 7682.

### 3. Python deps (py3)
```bash
pip install pylabrad twisted numpy pyopenssl
```
`pylabrad` is the py3 client/server library; `pyopenssl` is for TLS.

### 4. Environment (for the server and clients)
```bash
export LABRADHOST=localhost
export LABRADPASSWORD=<PW>       # same as the manager
export LABRAD_TLS=off            # if you disabled TLS on the manager (see above)
```

## Running

**Start the manager** (step 2 above), then in `Python_files/`:

```bash
# the server needs the bitstream path to configure the FPGA
export PULSER_BIT_PATH=/path/to/photon.bit
python pulser_labrad/pulser_server.py
```

It connects to the FPGA (ConfigureFPGA + MIG calibration), then registers with
the manager as `Pulser`. Then, in another shell:

```bash
python pulser_labrad/test_client.py
```

Expected: it lists channels, programs a small TTL sequence, runs it, and prints
`PASS`. That proves `scalabrad -> Pulser server -> pulser3 -> FPGA` end to end.

To exercise PMT counting over LabRAD (uses the on-FPGA synthetic source, so no
detector needed):

```bash
python pulser_labrad/pmt_client.py
```

Expected: Normal mode reports ~100 KC/s for a 100 kHz source over a 10 ms gate,
and a short timetag window returns photon arrival times in seconds.

## Notes / expected rough edges

- Written against the pylabrad **py3** API mirroring the legacy
  `servers/pulser/pulser_ok.py` patterns (`LabradServer`, `@setting`,
  `deferToThread`, `DeferredLock`). If pylabrad-py3 differs in a detail, the
  first run will surface it -- same write-here / verify-on-the-bench rhythm as
  the FPGA bring-ups.
- Blocking FPGA/USB calls run in a thread (`deferToThread`) so they don't stall
  the Twisted reactor.
- Setting name -> client method: spaces become underscores, lowercased --
  "Add TTL Pulse" is `p.add_ttl_pulse(...)`.
- `PULSER_BIT_PATH` must point at a valid `photon.bit`; the server configures
  the FPGA on startup.
