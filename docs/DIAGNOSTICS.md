# Investigating the two-flash symptom

The owner confirmed that v1.5 enables DSDS on coral, but observed this sequence: flash, boot Android with both IMEIs showing `00`, return to recovery, restore again, then both IMEIs work. An Android boot separated the two flashes. The previous EFS-only version was also reported to require two passes.

This supports investigating boot-time modem initialization. It does **not** prove that DSDS erased EFS or identify a particular reset flag. The installer already flushes and verifies the four backup images in recovery before reporting success. A valid recovery readback does not establish what the modem accepts or changes afterward.

**v1.5.1 adds evidence collection, not a verified single-flash repair.** It preserves the restore behavior and adds a before/after partition report in recovery RAM. No additional NV writes, reset-flag changes or Android boot scripts are introduced.

## Capture a failed first boot

Use these steps if the symptom occurs during your next planned install. There is no need to reset a currently working phone just to collect evidence. USB debugging must already be enabled and the computer authorized in Android.

The read-only collector is in `tools/capture_diagnostics.py` in both the source download and a newly built personal ZIP. Extract it on the computer and run from that extracted folder. It uses Python 3.10+ and `adb` on PATH; no Python packages or Android root are required for the Android log capture.

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

Changing the order of two offline writes cannot establish what the following Android boot will do. A genuine single-flash fix needs a confirmed cause from these captures. The currently reported working fallback remains flash, boot Android, return to recovery, restore again.
