// Tells the FatFs SD card library how the Adafruit micro SD breakout is wired.
// SPI0: SCK = GP18, MOSI (breakout SI) = GP19, MISO (breakout SO) = GP16, CS = GP17
// Card detect (breakout DET) = GP22: grounded with no card, pulled high when one is inserted
#include "hw_config.h"

static spi_t spi = {
    .hw_inst = spi0,
    .sck_gpio = 18,
    .mosi_gpio = 19,
    .miso_gpio = 16,
    .baud_rate = 12500 * 1000,  // 12.5 MHz is comfortable for breadboard wiring
};

static sd_spi_if_t spi_if = {
    .spi = &spi,
    .ss_gpio = 17,
};

static sd_card_t sd_card = {
    .type = SD_IF_SPI,
    .spi_if_p = &spi_if,
    .use_card_detect = true,
    .card_detect_gpio = 22,
    .card_detected_true = 1,
    // If DET isn't wired, the pull-up makes it look like a card is always there and
    // write errors are used to notice a removed card instead
    .card_detect_use_pull = true,
    .card_detect_pull_hi = true,
};

size_t sd_get_num() { return 1; }

sd_card_t* sd_get_by_num(size_t num) { return num == 0 ? &sd_card : NULL; }
