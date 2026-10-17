Diagnostic update for **Pixel 4 XL (coral)**, maintained by **Hecker**.

The owner confirmed DSDS activation from the recovery ZIP. However, the first Android boot still showed both IMEIs as `00`; returning to recovery and flashing the same ZIP again restored both. An Android boot separated the two flashes. The cause remains unconfirmed.

- Add `partition-state.tsv` with expected, pre-restore and verified post-restore digests in recovery RAM.
- Add a read-only ADB collector for first-boot radio logs and recovery partition digests/metadata, with Windows CMD instructions.
- Optionally compare recovery digests against a personal restore ZIP on the computer, without exporting raw EFS images.
- Include the collector and diagnostic guide in locally generated personal ZIPs.
- Keep the existing restore writes and DSDS configuration behavior. No guessed modem/NV writes, reset-flag modifications or Android boot scripts are added.

**This release does not claim to fix the two-flash requirement.** Failed-boot evidence is needed to distinguish normal modem writes, rejected provisioning and radio/configuration changes. Different partition hashes alone do not prove corruption.

The source download is not recovery-flashable. Build your private ZIP from your original handset's own four backups. Source releases and CI artifacts contain no personal modem data. Logs may contain identifiers: send captures privately, not in public GitHub issues.

Pixel 4 / flame is not supported. This remains a prerelease and does not establish factory-reset permanence or bootloader-relocking support.
