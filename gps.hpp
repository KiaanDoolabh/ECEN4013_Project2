// Driver for the Adafruit Mini GPS PA1010D (MediaTek MT3333) over I2C.
// The module streams NMEA sentences; reading it at address 0x10 returns the next
// bytes of that stream, padded with '\n' when nothing new is waiting.
#pragma once
#include <cstddef>
#include <cstdint>
#include "hardware/i2c.h"

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

class Pa1010d {
public:
    static constexpr uint8_t ADDRESS = 0x10;

    // The bus must already be set up with i2c_init() and its pins
    explicit Pa1010d(i2c_inst_t* i2c) : i2c_(i2c) {}

    // Checks the module answers and configures it. False means check wiring.
    bool init();

    // Drains bytes waiting in the module. True if a new sentence updated fix().
    bool poll();

    // Sends a PMTK command, e.g. "PMTK220,1000". Adds the '$', checksum and CRLF.
    bool send_command(const char* body);

    const GpsFix& fix() const { return fix_; }
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
};
