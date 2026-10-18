# Floral EFS Toolkit

**Personal EFS restore packages for Pixel 4 XL (coral), with optional DSDS configuration.**

Maintained by **Hecker** · [Updates](https://t.me/pixel4seriesupdates) · [Support](https://t.me/Pixel4Roms)

Add your own `modemst1`, `modemst2`, `fsg` and `fsc` backups to the public OrangeFox/TWRP ZIP, then flash it on the original handset. It restores those bytes directly in recovery and verifies every partition after writing. Both `persist.radio.multisim.config=dsds` and `persist.vendor.mdm.multisim.cfg=dsds` are saved together, keeping Android's requested mode and the saved modem mode consistent.

**The public recovery ZIP contains no EFS files.** Download the **TEMPLATE.zip** asset from the [latest release](https://github.com/its-hecker/floral-efs-toolkit/releases/latest), add your own four backups inside `efs_backup/`, then flash the personalized ZIP. An empty or incomplete template is rejected before restore writes. No Python is needed for this method. The separate source ZIP is for developers and is not recovery-flashable.

## Support and status

| Item | Status |
| --- | --- |
| Pixel 4 XL / `coral` | Supported target; device and partition sizes checked at flash time |
| Pixel 4 / `flame` | Not supported by this release |
| EFS restore and automatic DSDS | Maintainer confirmed v1.5.2 works after the two-flash fix; v1.5.3 publishes that logic with a user-filled template |
| Magisk / KernelSU | Not required by the recovery ZIP |
| Factory-reset permanence | Not provided; a later wipe may require restore again |

The device check identifies the model, not the individual phone. File sizes and hashes do not prove that backups belong to the right handset or contain valid provisioning. This toolkit copies existing backups; it does not generate or rewrite identifiers.

## Prepare the public ZIP (no Python)

1. Download `Floral-EFS-Restore-coral-v1.5.3-TEMPLATE.zip` from the [release assets](https://github.com/its-hecker/floral-efs-toolkit/releases/latest). Do not choose GitHub's automatic source-code downloads for flashing.
2. Open the ZIP in an archive manager. Open its **`efs_backup/`** directory and add the following raw backups from the exact handset you intend to restore:

| Path inside the ZIP | Required bytes |
| --- | ---: |
| `efs_backup/modemst1` | 2,097,152 |
| `efs_backup/modemst2` | 2,097,152 |
| `efs_backup/fsg` | 2,097,152 |
| `efs_backup/fsc` | 131,072 |

3. Save the updated ZIP and copy it to the phone. Keep the names exactly as listed, without `.img`, `.bin` or `.txt` extensions. Do not put them in another subfolder. The included `efs_backup/README.txt` can stay.
4. Follow the OrangeFox instructions below. Once filled, this ZIP contains your personal modem data: keep it private.

If extracting and repacking, select the extracted folder's **contents**, so `META-INF/`, `install/` and `efs_backup/` stay directly at the ZIP root. Use ZIP format. Do not wrap everything in another folder. Do not edit installer scripts or the included `SHA256SUMS` file.

Only raw partition images are accepted; a QCN or compressed backup is not a substitute. The template calculates hashes from the supplied images before restoring and verifies the written partitions against them. It cannot establish backup ownership or working provisioning.

## Optional: build a ZIP with embedded backup checksums

Install **Python 3.10 or later**, download and extract the source release, and place the four raw backups in a local folder using the filenames and sizes above. Building uses only Python's standard library.

Run from the extracted toolkit folder. On Windows CMD, for example:

```bat
py -3 build.py --backup-dir "C:\Users\YourName\Documents\coral-backups"
```

On Linux or macOS:

```sh
python3 build.py --backup-dir "$HOME/coral-backups"
```

The builder writes `dist/Floral-EFS-Restore-coral-v1.5.3-DSDS-PERSONAL.zip`. It copies backups unchanged, embeds their checksums, verifies the completed archive and refuses to overwrite an existing output. The backups are already included in this output; do not replace them manually afterward.

For an EFS-only package that leaves DSDS unchanged and does not require readable Data:

```bat
py -3 build.py --backup-dir "C:\Users\YourName\Documents\coral-backups" --no-dsds
```

Use `--output "path\new-name.zip"` when you want a different output filename. **Keep the generated ZIP and your raw backups private.** Do not upload them to an issue, public repository or Actions artifact.

## Flash in OrangeFox

1. Complete the ROM installation and its required wipes first. Preserve or reinstall recovery according to that ROM's instructions.
2. For a package with DSDS enabled, Android must have initialized Data and the modem after the last Format Data. If necessary, boot Android, let it finish starting, then return to OrangeFox. The existing modem initialization marker must be present; the installer does not create it. **You do not need to open the dialer or manually toggle DSDS.**
3. Mount/decrypt Data in OrangeFox if needed. Select your personal ZIP and swipe to flash, or use recovery's ADB Sideload screen.
4. Wait for `SUCCESS: all four partitions restored and verified.` A DSDS package must also report `SUCCESS: DSDS enabled for the next Android boot.`
5. Reboot System and check both IMEIs and cellular service. The installer verifies stored bytes and the saved setting; actual modem activation is checked in Android.

Complete all wipes before restoring. If Data was freshly formatted and the settings database is absent or unreadable, the DSDS installer stops **before any EFS write**. Initialize Android or unlock Data as appropriate, then retry. An EFS-only package does not change DSDS.

The four target partitions are shared between slots. This ZIP does not change the active slot or flash boot, recovery, system, vendor, persist or bootloader images. It does not establish that a ROM supports bootloader relocking.

## First boot shows `00`, second restore works

The captured failed boot reports Android requesting DSDS while the saved modem mode is `ss`. `rmt_storage` detects an SS-to-DSDS change and explicitly clears both modem stores. Later in that same boot the modem saves its mode as DSDS, explaining the observed benefit of restoring again afterward.

v1.5.2 addresses this mismatch by saving both persistent mode properties together and requiring the existing modem initialization marker. **The maintainer tested that build and confirmed it works.** v1.5.3 keeps that restore/DSDS logic and adds the public template. This confirmation concerns the tested coral handset, not every ROM or device. See [diagnostics](docs/DIAGNOSTICS.md) if the symptom recurs.

## Checks and failure handling

- Requires recovery root, coral identity and inactive known modem services.
- Checks exact source and target sizes, write protection and mount state before restoring. Templates calculate hashes of user-supplied files; locally built personal ZIPs additionally check embedded backup hashes.
- Saves verified pre-restore copies of all four partitions in recovery RAM.
- Flushes and hashes each partition after writing; a failed write never produces overall success.
- For DSDS, requires the existing modem initialization marker, validates Android's protobuf database, preserves unrelated records and unknown fields, and stages both settings inside the existing encrypted directory.
- Checks ownership, permissions, SELinux label and content. Saves DSDS by atomic rename after all four EFS restores verify; attempts settings rollback if the DSDS readback fails.

If flashing fails, **keep recovery open** and copy out the printed log and pre-restore backups before rebooting. They are stored in `/tmp` and disappear on reboot. EFS writes are not automatically rolled back. If DSDS fails after EFS completed, the installer explicitly reports failure.

For troubleshooting, share the installer log after reviewing it for personal information. Do not share EFS images. See [implementation notes](docs/DESIGN.md) for the storage format and limitations.

## Development

The tests use synthetic backup bytes and regular files, never real block devices or personal modem data. The DSDS output is parsed independently with Google's protobuf library.

```sh
python3 -m pip install -r requirements-test.txt
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

On Linux, install `busybox-static` to exercise BusyBox ash, awk and filesystem applets as used by recovery. Set `EFS_TEST_BUSYBOX` to an explicit BusyBox path if needed. `python3 scripts/package_release.py` builds the allowlisted source archive and audited text-only recovery template. CI publishes these public assets and their checksums; personal backups are never inputs to that job.

## Credits and license

Original toolkit and recovery integration: **Hecker**. Android's public init, persistent-property and coral device sources document the DSDS startup path. OrangeFox/TWRP provide the recovery environment. BusyBox and Google's protobuf library are used for local verification and are not bundled in personal restore ZIPs.

MIT license for this repository's original code. See [LICENSE](LICENSE) and [references](docs/DESIGN.md#references).
