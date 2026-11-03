// CSV logger on a micro SD card (FatFs over SPI, wiring in hw_config.c).
// Every boot and every time a card is put back in, it starts a new file:
// LOG000.CSV, LOG001.CSV, ... picking the next number not already on the card.
#pragma once
#include <cstdint>
#include "ff.h"
#include "pico/time.h"

class SdLogger {
public:
    enum class Event { None, Started, Removed, Failed };

    explicit SdLogger(const char* header) : header_(header) {}

    // Call often. Notices the card going in or out, and opens a new file when it goes in.
    Event update();

    // Appends one line (should end in '\n'). Saves to the card at most once a second.
    void write(const char* line);

    // What the DET pin says right now (always true if DET isn't wired)
    bool card_present();

    bool logging() const { return open_; }
    const char* filename() const { return filename_; }
    uint32_t rows() const { return rows_; }
    const char* error() const { return error_; }

private:
    bool start();
    void stop();

    const char* header_;
    FATFS fs_;
    FIL file_;
    bool driver_ready_ = false;
    bool open_ = false;
    bool failure_reported_ = false;
    bool lost_by_write_error_ = false;
    bool card_was_in_ = false;
    absolute_time_t retry_at_ = nil_time;
    absolute_time_t next_sync_ = nil_time;
    char filename_[16] = {};
    uint32_t rows_ = 0;
    const char* error_ = "";
};
