#include "gps.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "pico/stdlib.h"

namespace {

// NMEA checksum = XOR of every character between '$' and '*'
uint8_t nmea_checksum(const char* s, size_t n) {
    uint8_t sum = 0;
    for (size_t i = 0; i < n; ++i) sum ^= static_cast<uint8_t>(s[i]);
    return sum;
}

// NMEA writes positions as (d)ddmm.mmmm
double nmea_to_degrees(const char* value, const char* hemisphere) {
    if (!*value) return 0;
    double raw = atof(value);
    int degrees = static_cast<int>(raw / 100);
    double result = degrees + (raw - degrees * 100) / 60.0;
    return (*hemisphere == 'S' || *hemisphere == 'W') ? -result : result;
}

uint8_t two_digits(const char* s) { return (s[0] - '0') * 10 + (s[1] - '0'); }

// Constellations by their one-letter code, in the order used_ is indexed
constexpr const char* SYSTEMS = "GRECJ";

int system_index(char system) {
    const char* p = system ? strchr(SYSTEMS, system) : nullptr;
    return p ? p - SYSTEMS : -1;
}

// Talker ID (the two letters after '$') -> constellation code; 0 for GN (combined) or unknown
char system_from_talker(const char* talker) {
    switch (talker[1]) {
        case 'P': return 'G';  // GP
        case 'L': return 'R';  // GL
        case 'A': return 'E';  // GA
        case 'B': case 'D': return 'C';  // GB / BD
        case 'Q': return 'J';  // GQ / QZ
        default: return 0;
    }
}

constexpr uint32_t USED_LIST_MAX_AGE_MS = 3000;  // forget "used" if GSA stops coming

}  // namespace

bool Pa1010d::init() {
    uint8_t probe;
    if (i2c_read_timeout_us(i2c_, ADDRESS, &probe, 1, false, 10000) != 1) return false;

    send_command("PMTK314,0,1,0,1,1,2,0,0,0,0,0,0,0,0,0,0,0,0,0");  // RMC, GGA, GSA; GSV every 2nd fix
    send_command("PMTK220,1000");                                     // 1 Hz updates
    return true;
}

bool Pa1010d::send_command(const char* body) {
    char msg[96];
    int n = snprintf(msg, sizeof(msg), "$%s*%02X\r\n", body, nmea_checksum(body, strlen(body)));
    if (n <= 0 || n >= static_cast<int>(sizeof(msg))) return false;
    bool ok = i2c_write_timeout_us(i2c_, ADDRESS, reinterpret_cast<uint8_t*>(msg), n,
                                   false, 20000) == n;
    sleep_ms(10);  // give the module time to take in the command
    return ok;
}

bool Pa1010d::poll() {
    bool updated = false;
    // The module holds up to 255 bytes; read in chunks until we only get padding
    for (int chunk = 0; chunk < 8; ++chunk) {
        uint8_t buf[32];
        int n = i2c_read_timeout_us(i2c_, ADDRESS, buf, sizeof(buf), false, 10000);
        if (n != sizeof(buf)) break;
        bool got_data = false;
        for (uint8_t c : buf) {
            if (c != '\n') got_data = true;
            updated |= feed(static_cast<char>(c));
        }
        if (!got_data) break;
    }
    return updated;
}

bool Pa1010d::feed(char c) {
    if (c == '$') {
        len_ = 0;
    } else if (c == '\r' || c == '\n') {
        if (len_ == 0) return false;
        line_[len_] = '\0';
        len_ = 0;
        return handle_sentence();
    } else if (len_ == 0) {
        return false;  // skip anything before the first '$'
    }
    if (len_ < sizeof(line_) - 1) line_[len_++] = c;
    else len_ = 0;  // too long to be a real sentence, drop it
    return false;
}

bool Pa1010d::handle_sentence() {
    // line_ looks like "$GNGGA,...,*5B"
    char* star = strchr(line_, '*');
    if (!star || strlen(star) < 3) return false;
    if (nmea_checksum(line_ + 1, star - line_ - 1) != strtol(star + 1, nullptr, 16)) return false;
    strcpy(last_, line_);
    *star = '\0';

    // Split on commas in place, keeping empty fields
    const char* f[24];
    size_t count = 0;
    for (char* p = line_ + 1; count < 24;) {
        f[count++] = p;
        p = strchr(p, ',');
        if (!p) break;
        *p++ = '\0';
    }
    if (strlen(f[0]) != 5) return false;
    const char* type = f[0] + 2;  // skip the talker ID (GP, GN, GL...)

    if (strcmp(type, "GGA") == 0 && count >= 10) {
        fix_.quality = atoi(f[6]);
        fix_.satellites = atoi(f[7]);
        fix_.hdop = atof(f[8]);
        if (fix_.quality > 0) {
            fix_.latitude = nmea_to_degrees(f[2], f[3]);
            fix_.longitude = nmea_to_degrees(f[4], f[5]);
            fix_.altitude_m = atof(f[9]);
        }
        return true;
    }
    if (strcmp(type, "GSV") == 0 && count >= 4) {
        // Each constellation sends its own GSV set (GPGSV, GLGSV, ...); field 3 is how many
        // of its satellites are visible, so add them up
        const char* p = strchr("PLABQ", f[0][1]);
        if (p && *p) {
            in_view_[p - "PLABQ"] = atoi(f[3]);
            int total = 0;
            for (uint8_t n : in_view_) total += n;
            fix_.satellites_in_view = total;
        }
        handle_gsv(system_from_talker(f[0]), f, count);
        return true;
    }
    if (strcmp(type, "GSA") == 0 && count >= 18) {
        handle_gsa(system_from_talker(f[0]), f, count);
        return true;
    }
    if (strcmp(type, "RMC") == 0 && count >= 10) {
        if (strlen(f[1]) >= 6) {
            fix_.hour = two_digits(f[1]);
            fix_.minute = two_digits(f[1] + 2);
            fix_.second = two_digits(f[1] + 4);
        }
        fix_.valid = f[2][0] == 'A';
        if (fix_.valid) {
            fix_.latitude = nmea_to_degrees(f[3], f[4]);
            fix_.longitude = nmea_to_degrees(f[5], f[6]);
            fix_.speed_knots = atof(f[7]);
            fix_.course_deg = atof(f[8]);
        }
        if (strlen(f[9]) == 6) {
            fix_.day = two_digits(f[9]);
            fix_.month = two_digits(f[9] + 2);
            fix_.year = 2000 + two_digits(f[9] + 4);
        }
        return true;
    }
    return false;
}

void Pa1010d::handle_gsv(char system, const char* const* f, size_t count) {
    // $xxGSV,<total msgs>,<msg no>,<sats in view>,{<id>,<elevation>,<azimuth>,<snr>} x up to 4
    if (system_index(system) < 0) return;
    int total = atoi(f[1]), number = atoi(f[2]);
    if (number == 1) {
        staging_count_ = 0;
        staging_system_ = system;
    }
    if (system != staging_system_) return;  // missed the start of this set

    for (size_t i = 4; i + 3 < count && staging_count_ < sizeof(staging_) / sizeof(staging_[0]); i += 4) {
        if (!*f[i]) continue;
        staging_[staging_count_++] = {system, static_cast<uint16_t>(atoi(f[i])),
                                      static_cast<uint8_t>(atoi(f[i + 1])),
                                      static_cast<uint16_t>(atoi(f[i + 2])),
                                      static_cast<uint8_t>(atoi(f[i + 3])), false};
    }
    if (number != total) return;

    // Last sentence of the set: replace this constellation's satellites with the new list
    size_t kept = 0;
    for (size_t i = 0; i < sat_count_; ++i) {
        if (sats_[i].system != system) sats_[kept++] = sats_[i];
    }
    for (size_t i = 0; i < staging_count_ && kept < MAX_SATELLITES; ++i) sats_[kept++] = staging_[i];
    sat_count_ = kept;
    staging_system_ = 0;
}

void Pa1010d::handle_gsa(char talker_system, const char* const* f, size_t count) {
    // $xxGSA,<mode>,<fix type>,<id> x 12,<PDOP>,<HDOP>,<VDOP>[,<system id>]
    UsedList list = {};
    for (size_t i = 3; i < 15; ++i) {
        if (*f[i]) list.prn[list.count++] = atoi(f[i]);
    }

    // "GN" sentences cover several constellations, one sentence each; work out which this is
    char system = talker_system;
    if (!system && count >= 19 && *f[18]) {
        static const char by_id[] = {0, 'G', 'R', 'E', 'C', 'J'};
        int id = atoi(f[18]);
        system = id > 0 && id <= 5 ? by_id[id] : 0;
    }
    if (!system && list.count) {
        system = list.prn[0] >= 65 && list.prn[0] <= 96 ? 'R' : list.prn[0] <= 32 ? 'G' : 0;
    }
    int index = system_index(system);
    if (index < 0) return;

    list.updated = get_absolute_time();
    used_[index] = list;
}

size_t Pa1010d::satellites(GpsSatellite* out, size_t max) const {
    size_t n = 0;
    for (size_t i = 0; i < sat_count_ && n < max; ++i) {
        GpsSatellite s = sats_[i];
        int index = system_index(s.system);
        const UsedList& used = used_[index];
        bool fresh = used.count && absolute_time_diff_us(used.updated, get_absolute_time()) <
                                       USED_LIST_MAX_AGE_MS * 1000ll;
        s.used = false;
        for (uint8_t k = 0; fresh && k < used.count; ++k) {
            if (used.prn[k] == s.prn) s.used = true;
        }
        out[n++] = s;
    }
    return n;
}
