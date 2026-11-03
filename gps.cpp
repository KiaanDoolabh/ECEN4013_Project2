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

}  // namespace

bool Pa1010d::init() {
    uint8_t probe;
    if (i2c_read_timeout_us(i2c_, ADDRESS, &probe, 1, false, 10000) != 1) return false;

    send_command("PMTK314,0,1,0,1,0,5,0,0,0,0,0,0,0,0,0,0,0,0,0");  // RMC + GGA, GSV every 5th fix
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
