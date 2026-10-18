Stable public release for **Pixel 4 (flame) and Pixel 4 XL (coral)**, maintained by **Hecker**.

The maintainer tested v1.5.2 and confirmed the restore works with the DSDS fix. v1.5.4 retains that restore/DSDS logic and enables both flame and coral in the shared public template and read-only diagnostic collector. The maintainer reports both models supported.

The earlier public ZIP explicitly checked for coral. This release corrects that check, rejects conflicting model properties and keeps the exact partition-size checks. The optional builder supports `--device flame`; personal ZIPs remain restricted to their selected model. Backups from different phones are never interchangeable.

### Download and add your backups

Download **Floral-EFS-Restore-floral-v1.5.4-TEMPLATE.zip** from the assets below. **It contains no EFS images or dummy backups.** Open it in an archive manager and add your own raw backups at these exact paths inside the ZIP:

| ZIP path | Required bytes |
| --- | ---: |
| `efs_backup/modemst1` | 2,097,152 |
| `efs_backup/modemst2` | 2,097,152 |
| `efs_backup/fsg` | 2,097,152 |
| `efs_backup/fsc` | 131,072 |

Use backups from the **exact handset being restored**, with those filenames and no extensions. Save the updated ZIP. Keep `META-INF/`, `install/` and `efs_backup/` directly at the ZIP root; do not wrap them in an extra folder when repacking. The included `efs_backup/README.txt` explains the placement. No Python, script changes or checksum-file edits are required.

### Flash

1. Finish the ROM installation and all required wipes.
2. Android must have initialized Data and the modem after the last Format Data. If needed, boot Android once, let it finish starting, then return to OrangeFox. No dialer DSDS toggle is needed.
3. Mount/decrypt Data, then flash the ZIP containing your four backups.
4. Wait for both EFS and DSDS success messages. Reboot Android and check both IMEIs and cellular service. Do not wipe Data again after restoring.

The empty template, missing files and incorrectly sized images are rejected before restore writes. The template calculates hashes of your supplied images and verifies every written partition against them. It cannot verify backup ownership or working provisioning. Once filled, keep the ZIP private.

The DSDS fix saves both Android's requested mode and the saved modem mode as `dsds` together. Existing modem initialization is required; the installer never creates or changes reset markers. No Magisk/KernelSU module is needed.

The separate **Floral-EFS-Toolkit-v1.5.4-source.zip** contains source and the optional Python builder, which embeds known backup hashes. It is not recovery-flashable. Published assets and CI artifacts contain no personal EFS files or personal backup fingerprints.

Supports Pixel 4 (flame) and Pixel 4 XL (coral). Each handset requires its own original backups. Maintainer testing does not establish compatibility with every ROM, permanence through factory resets or bootloader-relocking support.
