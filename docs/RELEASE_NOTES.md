Public source release for **Pixel 4 XL (coral)**, maintained by **Hecker**.

- Build a personal OrangeFox/TWRP recovery ZIP locally from your own four modem backups.
- Restore `modemst1`, `modemst2`, `fsg` and `fsc` with model, size, checksum, write-protection and full readback checks.
- Save temporary pre-restore copies in recovery RAM.
- Optionally save DSDS for the next Android boot without a manual dialer toggle. This requires initialized, readable Data; a fresh Format Data may still need one Android boot before flashing.
- Build an EFS-only package with `--no-dsds` when you want to leave DSDS unchanged.
- No Magisk/KernelSU dependency, installed boot script or automatic reboot.

**The source download is not recovery-flashable.** Extract it and run `build.py` with backups from your original coral handset, then flash the generated personal ZIP. No personal EFS images are included in this repository or release. Do not publish your generated restore ZIP.

The original personal v1.4 EFS restore was reported working. The v1.5 DSDS addition has local automated coverage but still needs handset activation testing, so this source release is marked **prerelease**. Pixel 4 / flame is not supported by this release. This does not make the repair survive factory reset or establish bootloader-relocking support.

See the README for Windows CMD build commands, installation steps and troubleshooting.
