# Binary-safe editor for Android init's PersistentProperties protobuf.
# Input: od -An -v -tu1 FILE. Only the radio/modem DSDS records and their
# pending overrides change. Other records/unknown fields keep their bytes.
# Run with LC_ALL=C, -v expected_size=N, and -v mode=set or mode=check.

function fail(message) {
    print "Persistent-property check: " message > "/dev/stderr"
    failed = 1
    exit 1
}

function u32(limit,    value, scale, count, byte) {
    value = 0
    scale = 1
    for (count = 0; count < 5; count++) {
        if (pos > limit) fail("truncated varint")
        byte = bytes[pos++]
        if (count == 4 && byte > 15) fail("oversized varint")
        value += (byte % 128) * scale
        if (byte < 128) return value
        scale *= 128
    }
    fail("unterminated varint")
}

function skip(wire, limit,    count, byte, length_) {
    if (wire == 0) {
        for (count = 0; count < 10; count++) {
            if (pos > limit) fail("truncated scalar")
            byte = bytes[pos++]
            if (count == 9 && byte > 1) fail("oversized scalar")
            if (byte < 128) return
        }
        fail("unterminated scalar")
    } else if (wire == 1) {
        pos += 8
    } else if (wire == 2) {
        length_ = u32(limit)
        if (length_ > limit - pos + 1) fail("truncated field")
        pos += length_
    } else if (wire == 5) {
        pos += 4
    } else {
        fail("unsupported wire type")
    }
    if (pos > limit + 1) fail("truncated fixed field")
}

function text_at(start, length_,    result, index_) {
    result = ""
    for (index_ = start; index_ < start + length_; index_++) {
        result = result sprintf("%c", bytes[index_])
    }
    return result
}

function record(limit,    tag, number, wire, length_, name, value, name_index, target_index) {
    name = ""
    value = ""
    while (pos <= limit) {
        tag = u32(limit)
        number = int(tag / 8)
        wire = tag % 8
        if (number == 0) fail("invalid record tag")
        if (number == 1 || number == 2) {
            if (wire != 2) fail("invalid name/value encoding")
            length_ = u32(limit)
            if (length_ > limit - pos + 1) fail("truncated record string")
            if (number == 1) {
                if (length_ > 1024) fail("property name exceeds the supported size")
                for (name_index = pos; name_index < pos + length_; name_index++) {
                    if (bytes[name_index] < 33 || bytes[name_index] > 126) fail("non-ASCII property name")
                }
                name = text_at(pos, length_)
            }
            else if (length_ == 4) value = text_at(pos, length_)
            else value = ""
            pos += length_
        } else {
            skip(wire, limit)
        }
    }
    if (name !~ /^(persist\.|next_boot\.)[A-Za-z0-9_.:@-]+$/) {
        fail("invalid persistent-property name")
    }
    for (target_index = 1; target_index <= target_total; target_index++) {
        if (name == targets[target_index]) {
            target_count[target_index]++
            if (value == "dsds") dsds_count[target_index]++
            return 1
        }
        if (name == "next_boot." targets[target_index]) {
            pending_count[target_index]++
            return 1
        }
    }
    return 0
}

function emit_varint(value) {
    while (value >= 128) {
        printf "%c", (value % 128) + 128
        value = int(value / 128)
    }
    printf "%c", value
}

BEGIN {
    targets[1] = "persist.radio.multisim.config"
    targets[2] = "persist.vendor.mdm.multisim.cfg"
    target_total = 2
    max_size = 262144
    if (mode != "set" && mode != "check") fail("invalid editor mode")
    if (expected_size !~ /^[0-9]+$/ || expected_size > max_size) fail("invalid file size")
}

{
    for (index_ = 1; index_ <= NF; index_++) {
        if ($index_ !~ /^[0-9]+$/ || $index_ > 255) fail("invalid byte input")
        if (++total > max_size) fail("property file exceeds size limit")
        bytes[total] = $index_ + 0
    }
}

END {
    if (failed) exit 1
    if (total + 0 != expected_size + 0) fail("incomplete byte input")
    pos = 1
    while (pos <= total) {
        start = pos
        tag = u32(total)
        number = int(tag / 8)
        wire = tag % 8
        if (number == 0) fail("invalid top-level tag")
        if (number == 1) {
            if (wire != 2) fail("invalid property-record encoding")
            length_ = u32(total)
            if (length_ > total - pos + 1) fail("truncated property record")
            if (record(pos + length_ - 1)) removed[start] = pos - 1
        } else {
            skip(wire, total)
        }
    }
    if (mode == "check") {
        for (target_index = 1; target_index <= target_total; target_index++) {
            if (target_count[target_index] != 1 || dsds_count[target_index] != 1 || pending_count[target_index] != 0) {
                fail("DSDS setting is not unambiguous: " targets[target_index])
            }
        }
        exit 0
    }
    # No bytes are emitted until the entire existing file has been validated.
    for (index_ = 1; index_ <= total; index_++) {
        if (index_ in removed) index_ = removed[index_]
        else printf "%c", bytes[index_]
    }
    for (target_index = 1; target_index <= target_total; target_index++) {
        target = targets[target_index]
        printf "%c", 10
        emit_varint(2 + length(target) + 2 + 4)
        printf "%c", 10
        emit_varint(length(target))
        printf "%s", target
        printf "%c%c%s", 18, 4, "dsds"
    }
}
