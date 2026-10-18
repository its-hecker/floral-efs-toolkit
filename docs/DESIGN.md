# Implementation notes

## Packaging boundary

The public repository stores recovery templates and a local Python builder. A user can add their raw backups to `efs_backup/` inside the published empty recovery template, without Python. The alternative local builder accepts `--backup-dir`, validates exact lengths and embeds each image's SHA-256 hash in a personal ZIP. It never sends data over the network.

The stable public release includes an allowlisted source archive and an empty recovery template. `scripts/package_release.py` accepts no backup directory; it renders the installer using only public text, adds `efs_backup/README.txt` and audits the template against an exact entry allowlist. Every entry must be UTF-8 text without NULs and shorter than the smallest supported raw backup. No personal images or dummy images are packaged. Source archives exclude `dist`, backup folders, local dependencies, binaries and all personal ZIPs. CI publishes only these two audited assets and their checksums.

The public template uses `BACKUP_HASH_MODE=archive`: it calculates source image hashes in recovery before any restore writes and stores them in the validated target map for post-write readback. These are hashes of the supplied bytes, not independent known-good fingerprints. ZIP extraction checks CRC; source/target sizes and all other recovery checks still apply. A ZIP generated from `--backup-dir` uses `BACKUP_HASH_MODE=embedded` and additionally compares sources against the hashes recorded during building. The public template's `SHA256SUMS` covers its shipped installer/documentation files; adding personal images does not require editing that file.

## Recovery flow

The legacy `update-binary` shell entry point extracts only named payloads into a fresh recovery RAM directory. It invokes the restore functions after checking the package is complete. Device, recovery, backup and target checks precede EFS writes. Originals are saved and verified first. Known radio services must be stopped already; the installer never starts a modem service in recovery.

Every partition write is followed by a storage flush and full SHA-256 readback. Targets are unslotted `modemst1`, `modemst2`, `fsg` and `fsc`; symlink resolution must lead to four distinct block devices with the expected lengths. Backups are restored byte-for-byte, including zero-filled files supplied by their owner.

There is no automatic EFS rollback after a partial failure. The installer retains temporary originals and reports the failure rather than claiming success. Temporary copies disappear when recovery reboots.

## DSDS setting

Coral's init starts `vendor.qcrild2` when `persist.radio.multisim.config=dsds`. A plain recovery `setprop` does not establish that Android's on-disk persistent property file was changed. The optional DSDS path therefore edits the existing `/data/property/persistent_properties` protobuf offline.

The schema is a repeated property record, with field 1 for the name and field 2 for its value. The AWK editor consumes numeric bytes from `od`, validates the complete input before emitting output, preserves unrelated records and unknown fields byte-for-byte, then writes one unambiguous record each for `persist.radio.multisim.config=dsds` and `persist.vendor.mdm.multisim.cfg=dsds`. It removes duplicate records and pending `next_boot.` overrides only for those two settings. Unsupported or malformed input is rejected without replacing the original.

The original Android settings directory and database must exist, be readable and have expected file metadata. The installer does not create a plaintext substitute before Android has established its encryption policy. Property files are limited to 256 KiB; unsupported encodings or larger stores stop the install.

The modified database is staged in the existing property directory to inherit its encryption policy. File ownership is root:root, mode 0600, one hard link, with `u:object_r:property_data_file:s0`. DSDS is committed by atomic rename only after all EFS restores verify. A changed original database is not overwritten. A failed post-commit check triggers an attempt to restore the original settings.

The failed-boot evidence shows `rmt_storage` comparing Android's requested DSDS mode against a saved modem mode of `ss`, then clearing both modem stores. The modem saves `persist.vendor.mdm.multisim.cfg=dsds` later in that boot. Static inspection of the vendor `rmt_storage` artifact confirms that it compares these two properties and skips its mode-switch clear when they match. The second property is saved state used by that check; writing it does not itself prove the live modem changed mode.

The same artifact has a separate factory-reset check for `/data/vendor/modem_fdr/fdr_check`. A missing marker sets the clear flag even when the two modes agree. A DSDS package therefore requires this existing regular file, with no symlinks in its path, before EFS writes. It never creates, removes or edits the marker. Android must initialize it normally. An EFS-only package skips the entire Data/DSDS path, including this check, and retains the previous restore behavior.

The installer saves both settings in one atomic property-file replacement for the next boot. Live modem behavior cannot be verified in recovery. The maintainer subsequently tested v1.5.2 and confirmed that it works. v1.5.4 preserves the DSDS logic and accepts flame and coral in the shared public template. A consistent specific model identity and exact target partition sizes are required; a generic floral identity alone is insufficient. Personal builds default to coral and accept `--device flame` for a flame-specific package, preserving the cross-model guard. Support for both models does not establish compatibility with every handset/ROM or persistence through a subsequent factory reset.

## Validation scope

Tests use generated synthetic backups, mock device properties and regular files as partition targets. The production copy, hashing, protobuf editor and failure paths are exercised under BusyBox. SELinux and mount availability are simulated because the test host is not Android recovery. Google's protobuf parser independently validates generated property messages.

The personal v1.5.2 restore with the two-property DSDS fix was reported working by its owner. The maintainer also reports both models supported. The public template path is exercised for flame and coral using synthetic backups, actual extraction/copy/hashing and simulated block devices. Tests include rejection of other models, conflicting properties and mismatched personal-package targets. These checks do not validate every individual handset, ROM, carrier configuration, reset permanence or bootloader relocking.

## References

- [Coral init and DSDS triggers](https://android.googlesource.com/device/google/coral/+/refs/heads/android13-release/init.hardware.rc)
- [PersistentProperties schema](https://android.googlesource.com/platform/system/core/+/refs/heads/main/init/persistent_properties.proto)
- [Android init persistent-property implementation](https://android.googlesource.com/platform/system/core/+/refs/heads/main/init/persistent_properties.cpp)
- [Property-file SELinux context](https://android.googlesource.com/platform/system/sepolicy/+/refs/heads/android13-release/private/file_contexts)
- [Android Data directory initialization](https://android.googlesource.com/platform/system/core/+/refs/heads/android13-release/rootdir/init.rc)
- [Inspected vendor rmt_storage artifact](https://github.com/its-hecker/infinityx_cnb_vendor_google_flame/blob/lineage-24.0/proprietary/vendor/bin/rmt_storage) (Git blob `3bee21c7f3099102f92682b9820176b67cd79a25`; static inspection only, no binary modification or redistribution in this toolkit)

## Failed-boot evidence

v1.5.1 records a pipe-delimited `partition-state.tsv` beside the recovery log, with expected, pre-restore and verified post-restore hashes for each partition. The host-side collector reads Android logs and recovery digests/metadata; it never modifies the phone or collects raw EFS images. An optional comparison reads a personal restore ZIP on the computer and compares its image digests with the recovery readout. Different hashes alone do not prove corruption because normal modem operation writes persistent storage. See [diagnostics](DIAGNOSTICS.md).
