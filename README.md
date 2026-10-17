# Floral EFS Toolkit

**Personal EFS restore packages for Pixel 4 XL (coral), with optional DSDS configuration.**

Maintained by **Hecker** · [Updates](https://t.me/pixel4seriesupdates) · [Support](https://t.me/Pixel4Roms)

Build an OrangeFox/TWRP ZIP from your own `modemst1`, `modemst2`, `fsg` and `fsc` backups. The generated ZIP restores those bytes directly in recovery and verifies every partition after writing. By default, it also saves `persist.radio.multisim.config=dsds` so Android starts with the DSDS setting configured.

**No modem backups or ready-to-flash personal restore ZIPs are published here.** The release download contains the builder and source. It is not itself recovery-flashable. Every recovery ZIP must be built locally using backups from the same handset on which it will be flashed.

## Support and status

| Item | Status |
| --- | --- |
| Pixel 4 XL / `coral` | Supported target; device and partition sizes checked at flash time |
| Pixel 4 / `flame` | Not supported by this release |
| EFS restore | The maintainer's original v1.4 package was reported working on the original coral handset |
| Automatic DSDS setting | Owner confirmed activation on coral; first boot still showed `00` until a second restore |
| Magisk / KernelSU | Not required by the recovery ZIP |
| Factory-reset permanence | Not provided; a later wipe may require restore again |

The device check identifies the model, not the individual phone. File sizes and hashes do not prove that backups belong to the right handset or contain valid provisioning. This toolkit copies existing backups; it does not generate or rewrite identifiers.

## Build your personal ZIP

Install **Python 3.10 or later** on your computer. Building uses only the Python standard library; no root or Android SDK is required on the computer.

Download and extract the [latest source release](https://github.com/its-hecker/floral-efs-toolkit/releases), or clone this repository. Place the four raw backup files in a local folder, with these exact names and sizes:

| Filename | Required bytes |
| --- | ---: |
| `modemst1` | 2,097,152 |
| `modemst2` | 2,097,152 |
| `fsg` | 2,097,152 |
| `fsc` | 131,072 |

Run from the extracted toolkit folder. On Windows CMD, for example:

```bat
py -3 build.py --backup-dir "C:\Users\YourName\Documents\coral-backups"
```

On Linux or macOS:

```sh
python3 build.py --backup-dir "$HOME/coral-backups"
```

The builder writes `dist/Floral-EFS-Restore-coral-v1.5.1-DSDS-PERSONAL.zip`. It copies backups unchanged, embeds their checksums, verifies the completed archive and refuses to overwrite an existing output.

For an EFS-only package that leaves DSDS unchanged and does not require readable Data:

```bat
py -3 build.py --backup-dir "C:\Users\YourName\Documents\coral-backups" --no-dsds
```

Use `--output "path\new-name.zip"` when you want a different output filename. **Keep the generated ZIP and your raw backups private.** Do not upload them to an issue, public repository or Actions artifact.

## Flash in OrangeFox

1. Complete the ROM installation and its required wipes first. Preserve or reinstall recovery according to that ROM's instructions.
2. For a package with DSDS enabled, Android must have initialized Data after the last Format Data. If necessary, boot to Android's setup screen once, then return to OrangeFox. **You do not need to open the dialer or manually toggle DSDS.**
3. Mount/decrypt Data in OrangeFox if needed. Select your personal ZIP and swipe to flash, or use recovery's ADB Sideload screen.
4. Wait for `SUCCESS: all four partitions restored and verified.` A DSDS package must also report `SUCCESS: DSDS enabled for the next Android boot.`
5. Reboot System and check both IMEIs and cellular service. The installer verifies stored bytes and the saved setting; actual modem activation is checked in Android.

Complete all wipes before restoring. If Data was freshly formatted and the settings database is absent or unreadable, the DSDS installer stops **before any EFS write**. Initialize Android or unlock Data as appropriate, then retry. An EFS-only package does not change DSDS.

The four target partitions are shared between slots. This ZIP does not change the active slot or flash boot, recovery, system, vendor, persist or bootloader images. It does not establish that a ROM supports bootloader relocking.

## First boot shows `00`, second restore works

This sequence has been reported on the maintainer's coral. v1.5.1 adds a before/after partition report and a read-only Windows/Linux diagnostic collector. **It does not claim to fix the two-flash requirement.** See [failed-boot capture instructions](docs/DIAGNOSTICS.md). Capture Android radio logs while the first boot still shows `00`, then partition digests in recovery before the second restore. No further reset is needed on a currently working phone.

## Checks and failure handling

- Requires recovery root, coral identity and inactive known modem services.
- Checks every backup hash, exact source and target sizes, write protection and mount state before restoring.
- Saves verified pre-restore copies of all four partitions in recovery RAM.
- Flushes and hashes each partition after writing; a failed write never produces overall success.
- For DSDS, validates Android's protobuf database, preserves unrelated records and unknown fields, and stages the change inside the existing encrypted directory.
- Checks ownership, permissions, SELinux label and content. Saves DSDS by atomic rename after all four EFS restores verify; attempts settings rollback if the DSDS readback fails.

If flashing fails, **keep recovery open** and copy out the printed log and pre-restore backups before rebooting. They are stored in `/tmp` and disappear on reboot. EFS writes are not automatically rolled back. If DSDS fails after EFS completed, the installer explicitly reports failure.

For troubleshooting, share the installer log after reviewing it for personal information. Do not share EFS images. See [implementation notes](docs/DESIGN.md) for the storage format and limitations.

## Development

The tests use synthetic backup bytes and regular files, never real block devices or personal modem data. The DSDS output is parsed independently with Google's protobuf library.

```sh
python3 -m pip install -r requirements-test.txt
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

On Linux, install `busybox-static` to exercise BusyBox ash, awk and filesystem applets as used by recovery. Set `EFS_TEST_BUSYBOX` to an explicit BusyBox path if needed. CI requires BusyBox and publishes only an allowlisted source archive.

## Credits and license

Original toolkit and recovery integration: **Hecker**. Android's public init, persistent-property and coral device sources document the DSDS startup path. OrangeFox/TWRP provide the recovery environment. BusyBox and Google's protobuf library are used for local verification and are not bundled in personal restore ZIPs.

MIT license for this repository's original code. See [LICENSE](LICENSE) and [references](docs/DESIGN.md#references).
