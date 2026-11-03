#include "imu.hpp"
#include <cmath>
#include "pico/stdlib.h"

namespace {

// SHTP channels
constexpr uint8_t CHANNEL_EXECUTABLE = 1;  // reset / "reset complete"
constexpr uint8_t CHANNEL_CONTROL = 2;     // SH-2 commands like Set Feature
constexpr uint8_t CHANNEL_REPORTS = 3;     // sensor readings
constexpr uint8_t CHANNEL_WAKE_REPORTS = 4;

// SH-2 report IDs
constexpr uint8_t REPORT_ACCELEROMETER = 0x01;
constexpr uint8_t REPORT_GYROSCOPE = 0x02;
constexpr uint8_t REPORT_ROTATION_VECTOR = 0x05;
constexpr uint8_t REPORT_TIMESTAMP_REBASE = 0xFA;
constexpr uint8_t REPORT_BASE_TIMESTAMP = 0xFB;
constexpr uint8_t SET_FEATURE_COMMAND = 0xFD;

constexpr uint32_t REPORT_INTERVAL_US = 50000;  // 20 Hz

// Length of each input report, so several packed into one packet can be split apart
size_t report_length(uint8_t id) {
    switch (id) {
        case REPORT_TIMESTAMP_REBASE: return 5;
        case 0x01: case 0x02: case 0x03: case 0x04: case 0x06: return 10;  // 3-axis sensors
        case 0x08: return 12;                                               // game rotation vector
        case 0x05: case 0x09: return 14;                                    // rotation vectors
        default: return 0;
    }
}

int16_t le16(const uint8_t* p) { return static_cast<int16_t>(p[0] | (p[1] << 8)); }

// Readings are fixed-point with a per-report number of fraction bits ("Q point")
float fixed(const uint8_t* p, int q) { return le16(p) / static_cast<float>(1 << q); }

constexpr float RAD_TO_DEG = 57.2957795f;

}  // namespace

bool Bno085::init() {
    // Try both addresses for up to a second, since the sensor can be slow to answer after power-up
    const uint8_t candidates[] = {ADDRESS, ADDRESS_ALT};
    uint8_t header[4];
    bool found = false;
    absolute_time_t give_up_search = make_timeout_time_ms(1000);
    while (!found && !time_reached(give_up_search)) {
        for (uint8_t a : candidates) {
            if (i2c_read_timeout_us(i2c_, a, header, sizeof(header), false, 20000) == 4) {
                address_ = a;
                found = true;
                break;
            }
        }
        if (!found) sleep_ms(50);
    }
    if (!found) return false;

    // Soft reset so we start from a known state, then drain the start-up messages
    uint8_t reset = 1;
    write_packet(CHANNEL_EXECUTABLE, &reset, 1);
    absolute_time_t give_up = make_timeout_time_ms(1000);
    reset_seen_ = false;
    while (!reset_seen_ && !time_reached(give_up)) {
        if (read_packet() <= 0) sleep_ms(10);
    }
    reset_seen_ = false;
    enable_reports();
    return true;
}

bool Bno085::poll() {
    new_data_ = false;
    for (int i = 0; i < 10 && read_packet() > 0; ++i) {}
    // The sensor forgets its settings if it resets itself, so turn the reports back on
    if (reset_seen_) {
        reset_seen_ = false;
        enable_reports();
    }
    return new_data_;
}

int Bno085::read_packet() {
    // Every read starts with the header, so peek at it to learn the length,
    // then read again for the whole packet
    uint8_t header[4];
    if (i2c_read_timeout_us(i2c_, address_, header, sizeof(header), false, 5000) != 4) return -1;
    size_t len = (header[0] | (header[1] << 8)) & 0x7FFF;  // top bit = continuation
    if (len <= 4 || len == 0x7FFF) return 0;

    if (len > sizeof(packet_)) len = sizeof(packet_);  // the rest arrives as a continuation
    if (i2c_read_timeout_us(i2c_, address_, packet_, len, false, 20000) != static_cast<int>(len))
        return -1;

    bool continuation = header[1] & 0x80;
    if (!continuation) handle_packet(header[2], packet_ + 4, len - 4);
    return 1;
}

bool Bno085::write_packet(uint8_t channel, const uint8_t* payload, size_t len) {
    uint8_t msg[32];
    size_t total = len + 4;
    if (total > sizeof(msg) || channel >= sizeof(sequence_)) return false;
    msg[0] = total & 0xFF;
    msg[1] = total >> 8;
    msg[2] = channel;
    msg[3] = sequence_[channel]++;
    for (size_t i = 0; i < len; ++i) msg[4 + i] = payload[i];
    return i2c_write_timeout_us(i2c_, address_, msg, total, false, 20000) == static_cast<int>(total);
}

void Bno085::enable_report(uint8_t report_id, uint32_t interval_us) {
    uint8_t cmd[17] = {SET_FEATURE_COMMAND, report_id};
    cmd[5] = interval_us & 0xFF;  // bytes 5-8: report interval in microseconds, little-endian
    cmd[6] = (interval_us >> 8) & 0xFF;
    cmd[7] = (interval_us >> 16) & 0xFF;
    cmd[8] = interval_us >> 24;
    write_packet(CHANNEL_CONTROL, cmd, sizeof(cmd));
    sleep_ms(10);
}

void Bno085::enable_reports() {
    enable_report(REPORT_ROTATION_VECTOR, REPORT_INTERVAL_US);
    enable_report(REPORT_ACCELEROMETER, REPORT_INTERVAL_US);
    enable_report(REPORT_GYROSCOPE, REPORT_INTERVAL_US);
}

void Bno085::handle_packet(uint8_t channel, const uint8_t* p, size_t len) {
    if (channel == CHANNEL_EXECUTABLE) {
        if (len >= 1 && p[0] == 1) reset_seen_ = true;
        return;
    }
    if (channel != CHANNEL_REPORTS && channel != CHANNEL_WAKE_REPORTS) return;

    // A packet can hold several reports back to back, usually after a base timestamp
    size_t i = 0;
    if (len >= 5 && p[0] == REPORT_BASE_TIMESTAMP) i = 5;
    while (i < len) {
        size_t size = report_length(p[i]);
        if (size == 0 || i + size > len) break;
        const uint8_t* r = p + i;  // r[0] id, r[1] sequence, r[2] status, r[3] delay, r[4..] values

        switch (r[0]) {
            case REPORT_ACCELEROMETER:
                for (int a = 0; a < 3; ++a) data_.accel[a] = fixed(r + 4 + 2 * a, 8);
                new_data_ = true;
                break;
            case REPORT_GYROSCOPE:
                for (int a = 0; a < 3; ++a) data_.gyro[a] = fixed(r + 4 + 2 * a, 9);
                new_data_ = true;
                break;
            case REPORT_ROTATION_VECTOR: {
                float x = fixed(r + 4, 14), y = fixed(r + 6, 14), z = fixed(r + 8, 14), w = fixed(r + 10, 14);
                data_.qi = x; data_.qj = y; data_.qk = z; data_.qr = w;
                data_.accuracy = r[2] & 0x03;
                data_.yaw = atan2f(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)) * RAD_TO_DEG;
                data_.pitch = asinf(fmaxf(-1.0f, fminf(1.0f, 2 * (w * y - z * x)))) * RAD_TO_DEG;
                data_.roll = atan2f(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)) * RAD_TO_DEG;
                new_data_ = true;
                break;
            }
            default:
                break;
        }
        i += size;
    }
}
