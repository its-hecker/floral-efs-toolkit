# Investigating the two-flash symptom

The owner confirmed that v1.5 enables DSDS on coral, but observed this sequence: flash, boot Android with both IMEIs showing `00`, return to recovery, restore again, then both IMEIs work. An Android boot separated the two flashes. The previous EFS-only version was also reported to require two passes.

## What the captured failed boot establishes

The Android capture contains a specific sequence:

1. `rmt_storage` reports `radio: dsds, modem:ss` and detects an SS-to-DSDS configuration change.
2. Its next reads report clearing both `/boot/modem_fs1` and `/boot/modem_fs2` due to FDR. Full writes to both stores follow.
3. The modem crashes with `RX_INIT FAILED due to NULL RF Cal`.
4. Later in the same boot, `modem_svc` saves `persist.vendor.mdm.multisim.cfg=dsds`.

The recovery capture before the second restore shows both `modemst` hashes differ from the private backup, while `fsg` and `fsc` match. The existing modem initialization marker predates the captured boot. These are stronger findings than a hash change alone: the boot log explicitly records the clear and the configuration mismatch. The later saved DSDS mode explains the reported benefit of a second restore after that Android boot.

The first restore's recovery log is not in these two captures: recovery RAM was lost on reboot. The captures establish the boot-time clear, not the precise before/after bytes of the first flash. Personal logs and partition hashes remain private.

## v1.5.2 fix and v1.5.3 public release

The recovery installer now saves both persistent mode properties as `dsds` in one atomic property-file replacement:

- `persist.radio.multisim.config`
- `persist.vendor.mdm.multisim.cfg`

Static inspection of the vendor `rmt_storage` artifact confirms that its mode-switch clear is skipped when these values agree. It also confirms a separate clear path when `/data/vendor/modem_fdr/fdr_check` is absent. The DSDS installer requires this existing Android-created marker before writing EFS; it never creates, deletes or edits the marker.

**The maintainer tested v1.5.2 and confirmed it works.** v1.5.3 retains that DSDS fix and publishes an empty recovery template that users fill with their own backups. No firmware patches, identifier changes, reset-marker writes or Android boot scripts are introduced. Supplied EFS images are restored byte-for-byte. An EFS-only package leaves the prior behavior intact.

On the next planned install, finish the ROM's wipes, let Android initialize Data and the modem once, then flash the personalized ZIP in recovery. The dialer toggle is unnecessary. Check both IMEIs and cellular service on the following Android boot. No reset is needed on a currently working phone solely to test the release.

## Capture a failed first boot

Use these steps if the symptom occurs during your next planned install. There is no need to reset a currently working phone just to collect evidence. USB debugging must already be enabled and the computer authorized in Android.

The read-only collector is in `tools/capture_diagnostics.py` in both the source download and a newly built personal ZIP. Extract it on the computer and run from that extracted folder. It uses Python 3.10+ and `adb` on PATH; no Python packages or Android root are required for the Android log capture. v1.5.2 adds the saved modem-mode property to the capture.

While Android still shows `00`, **before rebooting back to recovery**, run in Windows CMD:

```bat
py -3 tools\capture_diagnostics.py android --output efs-diagnostics-first-boot
```

This reads selected firmware/radio properties, the radio log, all available logcat buffers, and dmesg when permissions allow. A missing privileged dmesg is recorded as an optional failure. It does not enable debugging or change the phone's configuration.

Then return to OrangeFox:

```bat
adb reboot recovery
```

Exit any sideload screen. Before flashing the restore ZIP a second time, run:

```bat
py -3 tools\capture_diagnostics.py recovery --output efs-diagnostics-before-second-restore --restore-zip "C:\path\to\your-personal-restore.zip"
```

Replace the quoted path with your personal restore ZIP. The comparison is optional: omit `--restore-zip` if you only want the current digests. Recovery root is required for partition reads. Known radio services must be inactive. Data access is only used for optional file metadata; the collector does not mount, decrypt or modify Data.

The recovery capture reads the four partition sizes and SHA-256 hashes, relevant directory/flag metadata, and any existing toolkit logs/reports in recovery RAM. It **does not collect raw EFS images** or modify any file on the phone. Then use the existing restore procedure to recover service.

Send the two generated `efs-diagnostics-*.zip` files privately for analysis. Logs may contain identifiers, phone numbers or personal information. Do not attach them to a public GitHub issue. Existing output folders/archives are never overwritten. `capture.json` explicitly records failed reads and whether required captures completed.

## Optional recovery checkpoint after the first flash

If convenient, run the recovery collector immediately after the first flash and before booting Android, with a distinct output name such as `efs-diagnostics-after-first-flash`. This preserves the first restore log and partition report, which disappear when recovery reboots.

## Interpretation

- If the four partition hashes remain identical to the packaged backups while Android reports `00`, focus on modem acceptance, radio configuration and logs.
- Different hashes show that bytes changed. **That alone does not prove corruption or erasure**: normal modem operation also writes its storage. Correlate the differences with radio errors and reset/initialization messages.
- Flag-file presence or timestamps are evidence to compare, not instructions to create, delete or bypass those flags.

If the symptom recurs, inspect both mode properties, the explicit `rmt_storage` clear messages, the reset marker and the modem crash reason together. The previously reported fallback remains flash, boot Android, return to recovery, restore again. Maintainer confirmation concerns the tested coral handset and does not guarantee identical behavior on every ROM or phone.
