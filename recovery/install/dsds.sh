#!/sbin/sh
# Offline DSDS configuration. Never start Android's radio services in recovery.

dsds_property_file() {
    printf '%s\n' /data/property/persistent_properties
}

dsds_modem_marker() {
    printf '%s\n' /data/vendor/modem_fdr/fdr_check
}

dsds_data_mounted_rw() {
    while read -r DATA_SOURCE DATA_DEST DATA_FS DATA_OPTIONS DATA_REST; do
        [ "$DATA_DEST" = /data ] || continue
        case "$DATA_SOURCE:$DATA_FS" in /dev/*:ext4|/dev/*:f2fs) ;; *) return 1;; esac
        case ",$DATA_OPTIONS," in *,rw,*) return 0;; *) return 1;; esac
    done < /proc/mounts
    return 1
}

dsds_require_data() {
    if ! dsds_data_mounted_rw && command -v twrp >/dev/null 2>&1; then
        twrp mount /data >> "$LOG" 2>&1
    fi
    dsds_data_mounted_rw || die 'Mount/decrypt Data in OrangeFox, then flash again. No EFS writes started.'
}

dsds_context_ok() {
    DSDS_CONTEXT=$(ls -Zd "$1" 2>> "$LOG") || return 1
    case "$DSDS_CONTEXT" in *u:object_r:property_data_file:s0*) return 0;; *) return 1;; esac
}

dsds_metadata_ok() {
    [ "$(stat -c '%u:%g:%a:%h' "$1" 2>> "$LOG")" = 0:0:600:1 ] && dsds_context_ok "$1"
}

dsds_label_file() {
    chown 0:0 "$1" >> "$LOG" 2>&1 &&
        chmod 600 "$1" >> "$LOG" 2>&1 &&
        chcon u:object_r:property_data_file:s0 "$1" >> "$LOG" 2>&1 &&
        dsds_metadata_ok "$1"
}

dsds_cleanup() {
    if [ -n "${DSDS_STAGE:-}" ]; then
        rm -f "$DSDS_STAGE" >> "$LOG" 2>&1
        DSDS_STAGE=''
    fi
}

dsds_prepare() {
    DSDS_STAGE=''
    DSDS_COMMITTED=0
    DSDS_VERIFIED=0
    for DSDS_TOOL in awk od stat cp mv rm mktemp chmod chown chcon ls; do
        command -v "$DSDS_TOOL" >/dev/null 2>&1 || die "DSDS needs recovery tool: $DSDS_TOOL"
    done
    case "$(getprop ro.persistent_properties.ready)" in
        true|1) die 'Recovery has an active persistent-property service; offline DSDS editing is unsafe.';;
    esac
    dsds_require_data
    # rmt_storage also clears modem storage if this Android-created marker
    # is absent. Require existing initialization; never create/bypass it.
    DSDS_MODEM_MARKER=$(dsds_modem_marker)
    [ -f "$DSDS_MODEM_MARKER" ] && [ ! -L "$DSDS_MODEM_MARKER" ] &&
        [ "$(readlink -f "$DSDS_MODEM_MARKER")" = "$DSDS_MODEM_MARKER" ] ||
        die 'Modem initialization marker is missing or unsafe. Boot Android once, return to recovery, then flash. No EFS writes started.'
    DSDS_FILE=$(dsds_property_file)
    DSDS_DIR=${DSDS_FILE%/*}
    [ -d "$DSDS_DIR" ] && [ ! -L "$DSDS_DIR" ] &&
        [ "$(readlink -f "$DSDS_DIR")" = "$DSDS_DIR" ] ||
        die 'Android settings are not initialized. Boot Android once, return to recovery, then flash. No dialer toggle is needed.'
    [ -f "$DSDS_FILE" ] && [ ! -L "$DSDS_FILE" ] && [ -r "$DSDS_FILE" ] ||
        die 'Cannot read Android settings. Decrypt Data, or boot Android once after formatting and return to recovery.'
    dsds_metadata_ok "$DSDS_FILE" || die 'Cannot verify Android property-file permissions or SELinux label.'
    DSDS_OLD_HASH=$(file_sha256 "$DSDS_FILE") || die 'Cannot hash current Android settings.'
    DSDS_SNAPSHOT="$WORKDIR/before-restore/persistent_properties"
    cp -p "$DSDS_FILE" "$DSDS_SNAPSHOT" >> "$LOG" 2>&1 || die 'Cannot back up Android settings.'
    [ "$(file_sha256 "$DSDS_SNAPSHOT")" = "$DSDS_OLD_HASH" ] || die 'Android settings backup verification failed.'
    DSDS_SIZE=$(file_bytes "$DSDS_SNAPSHOT")
    case "$DSDS_SIZE" in ''|*[!0-9]*) die 'Cannot determine Android property-file size.';; esac
    [ "$DSDS_SIZE" -le 262144 ] || die 'Android property file exceeds the supported size limit.'
    od -An -v -tu1 "$DSDS_SNAPSHOT" > "$WORKDIR/properties-before.bytes" 2>> "$LOG" || die 'Cannot read Android property bytes.'
    LC_ALL=C awk -v expected_size="$DSDS_SIZE" -v mode=set -f "$WORKDIR/install/persistent-dsds.awk" \
        "$WORKDIR/properties-before.bytes" > "$WORKDIR/properties-dsds" 2>> "$LOG" ||
        die 'Android property file is invalid or unsupported; it was not overwritten.'
    DSDS_NEW_SIZE=$(file_bytes "$WORKDIR/properties-dsds")
    od -An -v -tu1 "$WORKDIR/properties-dsds" > "$WORKDIR/properties-after.bytes" 2>> "$LOG" || die 'Cannot check generated DSDS settings.'
    LC_ALL=C awk -v expected_size="$DSDS_NEW_SIZE" -v mode=check -f "$WORKDIR/install/persistent-dsds.awk" \
        "$WORKDIR/properties-after.bytes" >> "$LOG" 2>&1 || die 'Generated DSDS settings failed verification.'
    DSDS_NEW_HASH=$(file_sha256 "$WORKDIR/properties-dsds") || die 'Cannot hash DSDS settings.'
    DSDS_STAGE=$(mktemp "$DSDS_DIR/.hecker-dsds.XXXXXX") || die 'Cannot create DSDS settings on Data; check its mount/decryption.'
    cp "$WORKDIR/properties-dsds" "$DSDS_STAGE" >> "$LOG" 2>&1 || die 'Cannot stage DSDS settings.'
    dsds_label_file "$DSDS_STAGE" || die 'Cannot set safe DSDS file permissions and SELinux label.'
    [ "$(file_sha256 "$DSDS_STAGE")" = "$DSDS_NEW_HASH" ] || die 'Staged DSDS settings failed readback.'
    sync || die 'Cannot sync staged DSDS settings.'
    ui_print 'Radio and modem DSDS settings prepared together; other settings preserved.'
}

dsds_rollback() {
    DSDS_STAGE=$(mktemp "$DSDS_DIR/.hecker-dsds-rollback.XXXXXX") || return 1
    cp "$DSDS_SNAPSHOT" "$DSDS_STAGE" >> "$LOG" 2>&1 &&
        dsds_label_file "$DSDS_STAGE" &&
        [ "$(file_sha256 "$DSDS_STAGE")" = "$DSDS_OLD_HASH" ] &&
        sync && mv -f "$DSDS_STAGE" "$DSDS_FILE" >> "$LOG" 2>&1 || return 1
    DSDS_STAGE=''
    sync && [ "$(file_sha256 "$DSDS_FILE")" = "$DSDS_OLD_HASH" ] && dsds_metadata_ok "$DSDS_FILE"
}

dsds_commit() {
    [ "$(file_sha256 "$DSDS_FILE")" = "$DSDS_OLD_HASH" ] || die 'EFS restored, but Android settings changed during installation. DSDS was not committed; flash again.'
    mv -f "$DSDS_STAGE" "$DSDS_FILE" >> "$LOG" 2>&1 || die 'EFS restored, but saving DSDS failed; original Android settings remain.'
    DSDS_STAGE=''
    DSDS_COMMITTED=1
    if ! sync || [ "$(file_sha256 "$DSDS_FILE")" != "$DSDS_NEW_HASH" ] || ! dsds_metadata_ok "$DSDS_FILE"; then
        if dsds_rollback; then
            ui_print 'Original Android settings restored after DSDS verification failure.'
        else
            ui_print "DSDS rollback failed. Original settings copy: $DSDS_SNAPSHOT"
        fi
        die 'EFS restored, but DSDS verification failed. Keep recovery open and save the log.'
    fi
    DSDS_VERIFIED=1
    ui_print 'DSDS saved and verified for both radio and modem configuration.'
    dsds_cleanup
}
