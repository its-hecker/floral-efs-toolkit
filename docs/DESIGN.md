# Implementation notes

## Packaging boundary

The public repository stores recovery templates and a local Python builder. Backup bytes enter only through `--backup-dir`. The builder validates exact lengths, computes SHA-256 hashes, fills the shell template and verifies the completed personal ZIP. It never sends data over the network.

The public release is a source archive assembled from an explicit file allowlist. It excludes the `dist` folder, backup folders, local dependencies, binaries and all personal recovery ZIPs. GitHub's automatic source archives likewise contain only tracked public source.

## Recovery flow

The legacy `update-binary` shell entry point extracts only named payloads into a fresh recovery RAM directory. It invokes the restore functions after checking the package is complete. Device, recovery, backup and target checks precede EFS writes. Originals are saved and verified first. Known radio services must be stopped already; the installer never starts a modem service in recovery.

Every partition write is followed by a storage flush and full SHA-256 readback. Targets are unslotted `modemst1`, `modemst2`, `fsg` and `fsc`; symlink resolution must lead to four distinct block devices with the expected lengths. Backups are restored byte-for-byte, including zero-filled files supplied by their owner.

There is no automatic EFS rollback after a partial failure. The installer retains temporary originals and reports the failure rather than claiming success. Temporary copies disappear when recovery reboots.

## DSDS setting

Coral's init starts `vendor.qcrild2` when `persist.radio.multisim.config=dsds`. A plain recovery `setprop` does not establish that Android's on-disk persistent property file was changed. The optional DSDS path therefore edits the existing `/data/property/persistent_properties` protobuf offline.

The schema is a repeated property record, with field 1 for the name and field 2 for its value. The AWK editor consumes numeric bytes from `od`, validates the complete input before emitting output, preserves unrelated records and unknown fields byte-for-byte, then writes one unambiguous DSDS record. It removes only pending `next_boot.persist.radio.multisim.config` overrides of that same setting. Unsupported or malformed input is rejected without replacing the original.

The original Android settings directory and database must exist, be readable and have expected file metadata. The installer does not create a plaintext substitute before Android has established its encryption policy. Property files are limited to 256 KiB; unsupported encodings or larger stores stop the install.

The modified database is staged in the existing property directory to inherit its encryption policy. File ownership is root:root, mode 0600, one hard link, with `u:object_r:property_data_file:s0`. DSDS is committed by atomic rename only after all EFS restores verify. A changed original database is not overwritten. A failed post-commit check triggers an attempt to restore the original settings.

The installer saves the configuration for the next Android boot. It cannot verify live modem behavior in recovery. Android's framework and radio firmware may have other configuration requirements; the owner has confirmed v1.5 DSDS activation, but the first boot still needed a second EFS restore. An EFS-only package skips this entire Data/DSDS path.

## Validation scope

Tests use generated synthetic backups, mock device properties and regular files as partition targets. The production copy, hashing, protobuf editor and failure paths are exercised under BusyBox. SELinux and mount availability are simulated because the test host is not Android recovery. Google's protobuf parser independently validates generated property messages.

The previous personal v1.4 EFS restore was reported working by its owner. That confirmation does not validate other handsets, ROMs, carrier configurations, flame support, reset permanence or bootloader relocking.

## References

- [Coral init and DSDS triggers](https://android.googlesource.com/device/google/coral/+/refs/heads/android13-release/init.hardware.rc)
- [PersistentProperties schema](https://android.googlesource.com/platform/system/core/+/refs/heads/main/init/persistent_properties.proto)
- [Android init persistent-property implementation](https://android.googlesource.com/platform/system/core/+/refs/heads/main/init/persistent_properties.cpp)
- [Property-file SELinux context](https://android.googlesource.com/platform/system/sepolicy/+/refs/heads/android13-release/private/file_contexts)
- [Android Data directory initialization](https://android.googlesource.com/platform/system/core/+/refs/heads/android13-release/rootdir/init.rc)

## Failed-boot evidence

v1.5.1 records a pipe-delimited `partition-state.tsv` beside the recovery log, with expected, pre-restore and verified post-restore hashes for each partition. The host-side collector reads Android logs and recovery digests/metadata; it never modifies the phone or collects raw EFS images. An optional comparison reads a personal restore ZIP on the computer and compares its image digests with the recovery readout. Different hashes alone do not prove corruption because normal modem operation writes persistent storage. See [diagnostics](DIAGNOSTICS.md).
