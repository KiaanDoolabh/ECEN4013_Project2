// Driver for the Adafruit Mini GPS PA1010D (MediaTek MT3333) over I2C.
// The module streams NMEA sentences; reading it at address 0x10 returns the next
// bytes of that stream, padded with '\n' when nothing new is waiting.
#pragma once
#include <cstddef>
#include <cstdint>
#include "hardware/i2c.h"
#include "pico/time.h"

struct GpsFix {
    bool valid = false;          // RMC status 'A' = position is usable
    uint8_t quality = 0;         // GGA fix quality: 0 none, 1 GPS, 2 DGPS
    uint8_t satellites = 0;          // used in the fix (0 until there is one)
    uint8_t satellites_in_view = 0;  // visible across all constellations, even with no fix
    double latitude = 0;         // decimal degrees, south is negative
    double longitude = 0;        // decimal degrees, west is negative
    float altitude_m = 0;        // above mean sea level
    float hdop = 0;              // horizontal dilution of precision, lower is better
    float speed_knots = 0;
    float course_deg = 0;
    uint8_t hour = 0, minute = 0, second = 0;  // UTC
    uint8_t day = 0, month = 0;
    uint16_t year = 0;
};

// One satellite from the GSV (in view) and GSA (used in fix) sentences
struct GpsSatellite {
    char system;         // G = GPS, R = GLONASS, E = Galileo, C = BeiDou, J = QZSS
    uint16_t prn;        // satellite ID number as the receiver reports it
    uint8_t elevation;   // degrees above the horizon, 0-90
    uint16_t azimuth;    // compass bearing in degrees, 0 = north
    uint8_t snr;         // signal strength in dB-Hz, 0 = not being received
    bool used;           // part of the current position fix
};

class Pa1010d {
public:
    static constexpr uint8_t ADDRESS = 0x10;
    static constexpr size_t MAX_SATELLITES = 32;

    // The bus must already be set up with i2c_init() and its pins
    explicit Pa1010d(i2c_inst_t* i2c) : i2c_(i2c) {}

    // Checks the module answers and configures it. False means check wiring.
    bool init();

    // Drains bytes waiting in the module. True if a new sentence updated fix().
    bool poll();

    // Sends a PMTK command, e.g. "PMTK220,1000". Adds the '$', checksum and CRLF.
    bool send_command(const char* body);

    const GpsFix& fix() const { return fix_; }

    // Copies the satellites in view (up to max) into out, with used filled in. Returns how many.
    size_t satellites(GpsSatellite* out, size_t max) const;
    const char* last_sentence() const { return last_; }

private:
    bool feed(char c);
    bool handle_sentence();

    i2c_inst_t* i2c_;
    GpsFix fix_;
    char line_[128] = {};
    size_t len_ = 0;
    char last_[128] = {};
    uint8_t in_view_[5] = {};  // per constellation: GPS, GLONASS, Galileo, BeiDou, QZSS

    void handle_gsv(char system, const char* const* f, size_t count);
    void handle_gsa(char talker_system, const char* const* f, size_t count);

    // Satellites in view. Each constellation's GSV set is collected in staging_ and swapped in
    // once its last sentence arrives, so a half-received set is never reported.
    GpsSatellite sats_[MAX_SATELLITES] = {};
    size_t sat_count_ = 0;
    GpsSatellite staging_[20] = {};
    size_t staging_count_ = 0;
    char staging_system_ = 0;

    // IDs used in the fix, per constellation (same order as SYSTEMS in gps.cpp), from GSA
    struct UsedList {
        uint16_t prn[12];
        uint8_t count;
        absolute_time_t updated;
    };
    UsedList used_[5] = {};
};
