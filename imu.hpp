// Driver for the Adafruit BNO085 9-DOF orientation IMU over I2C.
// The BNO085 runs its own sensor fusion and talks Hillcrest's SHTP protocol:
// every message is a packet with a 4-byte header (length, channel, sequence number).
// We ask it for the reports we want with "Set Feature" commands, then read them as they arrive.
#pragma once
#include <cstddef>
#include <cstdint>
#include "hardware/i2c.h"

struct ImuData {
    float yaw = 0, pitch = 0, roll = 0;     // degrees, from the fused rotation vector
    float qi = 0, qj = 0, qk = 0, qr = 1;   // the same orientation as a quaternion
    uint8_t accuracy = 0;                   // 0 unreliable, 1 low, 2 medium, 3 high
    float accel[3] = {};                    // m/s^2 on x, y, z (includes gravity)
    float gyro[3] = {};                     // rad/s around x, y, z
    float mag[3] = {};                      // magnetic field in uT on x, y, z (calibrated)
};

class Bno085 {
public:
    static constexpr uint8_t ADDRESS = 0x4A;      // default
    static constexpr uint8_t ADDRESS_ALT = 0x4B;  // if the DI/ADR pad is bridged

    // The bus must already be set up with i2c_init() and its pins
    explicit Bno085(i2c_inst_t* i2c) : i2c_(i2c) {}

    // Looks for the sensor at either address, resets it and turns on the reports.
    // False means check wiring.
    bool init();

    uint8_t address() const { return address_; }

    // Reads any waiting packets. True if data() changed.
    bool poll();

    const ImuData& data() const { return data_; }

private:
    int read_packet();  // 1 = got a packet, 0 = nothing waiting, -1 = bus error
    void handle_packet(uint8_t channel, const uint8_t* payload, size_t len);
    bool write_packet(uint8_t channel, const uint8_t* payload, size_t len);
    void enable_report(uint8_t report_id, uint32_t interval_us);
    void enable_reports();

    i2c_inst_t* i2c_;
    uint8_t address_ = ADDRESS;
    uint8_t sequence_[6] = {};  // the sensor wants a separate counter per channel
    uint8_t packet_[512];
    bool reset_seen_ = false;
    bool new_data_ = false;
    ImuData data_;
};
