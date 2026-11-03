#include "logger.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "f_util.h"
#include "hw_config.h"

namespace {

constexpr const char* DRIVE = "0:";

// Returns n for names like "LOG042.CSV", or -1 for anything else
int log_number(const char* name) {
    if (strlen(name) != 10 || strncasecmp(name, "LOG", 3) != 0 || strcasecmp(name + 6, ".CSV") != 0)
        return -1;
    int n = 0;
    for (int i = 3; i < 6; ++i) {
        if (name[i] < '0' || name[i] > '9') return -1;
        n = n * 10 + (name[i] - '0');
    }
    return n;
}

}  // namespace

SdLogger::Event SdLogger::update() {
    if (!driver_ready_) driver_ready_ = sd_init_driver();
    if (!driver_ready_) return Event::None;

    if (lost_by_write_error_) {
        lost_by_write_error_ = false;
        return Event::Removed;
    }

    sd_card_t* sd = sd_get_by_num(0);
    bool card_in = sd_card_detect(sd);

    // A card was just inserted: give it a moment to seat, and report problems with it afresh
    if (card_in && !card_was_in_) {
        failure_reported_ = false;
        retry_at_ = make_timeout_time_ms(300);
    }
    card_was_in_ = card_in;

    if (open_ && !card_in) {
        stop();
        return Event::Removed;
    }
    if (!open_ && card_in && time_reached(retry_at_)) {
        if (start()) {
            failure_reported_ = false;
            return Event::Started;
        }
        // Keep trying quietly (needed when DET isn't wired, since we never see an insert)
        retry_at_ = make_timeout_time_ms(2000);
        if (!failure_reported_) {
            failure_reported_ = true;
            return Event::Failed;
        }
    }
    return Event::None;
}

bool SdLogger::card_present() {
    if (!driver_ready_) driver_ready_ = sd_init_driver();
    return driver_ready_ && sd_card_detect(sd_get_by_num(0));
}

bool SdLogger::start() {
    FRESULT fr = f_mount(&fs_, DRIVE, 1);
    if (fr != FR_OK) {
        error_ = FRESULT_str(fr);
        return false;
    }

    // Find the highest LOGnnn.CSV already on the card
    int highest = -1;
    DIR dir;
    FILINFO info;
    if (f_opendir(&dir, "0:/") == FR_OK) {
        while (f_readdir(&dir, &info) == FR_OK && info.fname[0]) {
            int n = log_number(info.fname);
            if (n > highest) highest = n;
        }
        f_closedir(&dir);
    }
    if (highest >= 999) {
        error_ = "card already has LOG999.CSV, clear some files";
        f_unmount(DRIVE);
        return false;
    }

    snprintf(filename_, sizeof(filename_), "LOG%03d.CSV", highest + 1);
    char path[24];
    snprintf(path, sizeof(path), "0:/%s", filename_);
    fr = f_open(&file_, path, FA_CREATE_NEW | FA_WRITE);
    if (fr != FR_OK) {
        error_ = FRESULT_str(fr);
        f_unmount(DRIVE);
        return false;
    }

    open_ = true;
    rows_ = 0;
    f_puts(header_, &file_);
    f_sync(&file_);
    next_sync_ = make_timeout_time_ms(1000);
    return true;
}

void SdLogger::stop() {
    f_close(&file_);  // fails harmlessly if the card is already gone
    f_unmount(DRIVE);
    open_ = false;
}

void SdLogger::write(const char* line) {
    if (!open_) return;

    UINT len = strlen(line), written = 0;
    FRESULT fr = f_write(&file_, line, len, &written);
    if (fr == FR_OK && written == len) {
        ++rows_;
        if (time_reached(next_sync_)) {
            fr = f_sync(&file_);  // flush to the card so a pulled card loses at most ~1 s
            next_sync_ = make_timeout_time_ms(1000);
        }
    }
    if (fr != FR_OK || written != len) {
        // Usually the card was pulled out with DET not wired. Drop it and try again
        // in a second; if a card is there by then it gets a new file.
        error_ = fr != FR_OK ? FRESULT_str(fr) : "card full";
        stop();
        lost_by_write_error_ = true;
        retry_at_ = make_timeout_time_ms(1000);
    }
}
