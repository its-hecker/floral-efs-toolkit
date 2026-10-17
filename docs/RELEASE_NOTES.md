Targeted DSDS test update for **Pixel 4 XL (coral)**, maintained by **Hecker**.

The captured failed boot identifies why the first restore was lost: Android requested DSDS while the saved modem mode still reported single SIM. `rmt_storage` detected the mode change and explicitly cleared both modem stores. The modem saved its mode as DSDS later in the same boot, which explains the reported benefit of restoring again afterward.

- Save `persist.radio.multisim.config=dsds` and `persist.vendor.mdm.multisim.cfg=dsds` together, keeping the requested and saved modem modes consistent before the next boot.
- Remove duplicate records and pending overrides only for these two settings; retain all unrelated settings and unknown protobuf fields.
- Require Android's existing modem initialization marker before EFS writes. Static inspection confirms that a missing marker independently triggers a clear; the installer never creates or modifies it.
- Add the saved modem-mode property to the read-only collector and update the diagnosis and testing guide.
- Exercise the observed radio-DSDS/modem-SS state in the installer tests, with independent protobuf validation, BusyBox coverage and rollback checks.

**Single-flash restoration still needs device confirmation.** This prerelease targets the observed clear; automated checks cannot establish modem acceptance on a real handset. EFS backups remain unchanged, and no firmware patches, identifier edits, reset-marker writes or Android boot scripts are introduced. No reset is needed on a currently working phone just to test the release.

The source download is not recovery-flashable. Build your private ZIP from your original handset's own four backups. Source releases and CI artifacts contain no personal modem data. Logs may contain identifiers: send captures privately, not in public GitHub issues.

Pixel 4 / flame is not supported. This remains a prerelease and does not establish factory-reset permanence or bootloader-relocking support.
