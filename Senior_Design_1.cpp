// Pico 2 board self-test / demo
//  - Onboard LED plays a pattern (heartbeat, Morse "GROUP 8", strobe)
//  - Press the BOOTSEL button to cycle patterns (no extra wiring needed)
//  - USB serial prints board info + live chip temperature once a second
//  - Reads an Adafruit PA1010D GPS and BNO085 IMU, both on I2C0 (SDA = GP4, SCL = GP5)
//  - Output goes over USB, HC-06 Bluetooth on UART0 (GP0/GP1), or both; type u / b / a to pick,
//    s to reprint the startup info. With no USB monitor connected it all goes over Bluetooth.
//  - Logs everything to a new CSV file on a micro SD card (SPI0, GP16-19, DET on GP22);
//    the LED switches to a triple-flash warning whenever nothing is being logged
#include <cstdio>
#include <cctype>
#include <cstring>
#include <ctime>
#include <vector>
#include "pico/stdlib.h"
#include "pico/stdio_usb.h"
#include "pico/unique_id.h"
#include "pico/aon_timer.h"
#include "hardware/adc.h"
#include "hardware/clocks.h"
#include "hardware/sync.h"
#include "hardware/structs/ioqspi.h"
#include "hardware/structs/sio.h"
#include "gps.hpp"
#include "console.hpp"
#include "imu.hpp"
#include "logger.hpp"

constexpr uint32_t LOG_INTERVAL_MS = 250;  // 4 rows a second

const char* const CSV_HEADER =
    "uptime_ms,utc_date,utc_time,gps_fix,latitude,longitude,altitude_m,satellites,sats_in_view,hdop,"
    "speed_knots,course_deg,yaw_deg,pitch_deg,roll_deg,heading_accuracy,"
    "accel_x,accel_y,accel_z,gyro_x,gyro_y,gyro_z,temp_c\n";

// One CSV row matching CSV_HEADER. Pass nullptr for a sensor that isn't connected;
// its columns are left empty, as are the position columns while the GPS has no fix.
void csv_row(char* out, size_t size, uint32_t uptime_ms, const GpsFix* gps,
             const ImuData* imu, float temp_c) {
    int n = snprintf(out, size, "%lu,", (unsigned long)uptime_ms);
    auto add = [&](const char* fmt, auto... args) {
        if (n >= 0 && n < (int)size) n += snprintf(out + n, size - n, fmt, args...);
    };

    if (gps && gps->year) add("%04u-%02u-%02u,", gps->year, gps->month, gps->day);
    else add(",");
    if (gps && gps->year) add("%02u:%02u:%02u,", gps->hour, gps->minute, gps->second);
    else add(",");
    if (gps && gps->valid) {
        add("1,%.7f,%.7f,%.1f,%u,%u,%.2f,%.2f,%.1f,", gps->latitude, gps->longitude, gps->altitude_m,
            gps->satellites, gps->satellites_in_view, gps->hdop, gps->speed_knots, gps->course_deg);
    } else if (gps) {
        add("0,,,,%u,%u,,,,", gps->satellites, gps->satellites_in_view);
    } else {
        add(",,,,,,,,,");
    }

    if (imu) {
        add("%.2f,%.2f,%.2f,%u,%.3f,%.3f,%.3f,%.4f,%.4f,%.4f,", imu->yaw, imu->pitch, imu->roll,
            imu->accuracy, imu->accel[0], imu->accel[1], imu->accel[2],
            imu->gyro[0], imu->gyro[1], imu->gyro[2]);
    } else {
        add(",,,,,,,,,,");
    }
    add("%.1f\n", temp_c);
}

// Plain Pico 2 drives the LED from GP25; the "W" boards route it through the wireless chip
#ifdef CYW43_WL_GPIO_LED_PIN
#include "pico/cyw43_arch.h"
#endif

class Led {
public:
    bool init() {
#ifdef CYW43_WL_GPIO_LED_PIN
        return cyw43_arch_init() == 0;
#else
        gpio_init(PICO_DEFAULT_LED_PIN);
        gpio_set_dir(PICO_DEFAULT_LED_PIN, GPIO_OUT);
        return true;
#endif
    }
    void set(bool on) {
        state_ = on;
#ifdef CYW43_WL_GPIO_LED_PIN
        cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, on);
#else
        gpio_put(PICO_DEFAULT_LED_PIN, on);
#endif
    }
    void toggle() { set(!state_); }
private:
    bool state_ = false;
};

// The BOOTSEL button shares the flash chip-select line, so reading it means briefly
// cutting off flash. This must run from RAM with interrupts disabled.
bool __no_inline_not_in_flash_func(bootsel_pressed)() {
    const uint CS_PIN_INDEX = 1;
    uint32_t flags = save_and_disable_interrupts();

    hw_write_masked(&ioqspi_hw->io[CS_PIN_INDEX].ctrl,
                    GPIO_OVERRIDE_LOW << IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_LSB,
                    IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_BITS);
    for (volatile int i = 0; i < 1000; ++i);

#if PICO_RP2040
    const uint32_t CS_BIT = 1u << 1;
#else
    const uint32_t CS_BIT = SIO_GPIO_HI_IN_QSPI_CSN_BITS;
#endif
    bool pressed = !(sio_hw->gpio_hi_in & CS_BIT);

    hw_write_masked(&ioqspi_hw->io[CS_PIN_INDEX].ctrl,
                    GPIO_OVERRIDE_NORMAL << IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_LSB,
                    IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_BITS);
    restore_interrupts(flags);
    return pressed;
}

float chip_temp_c() {
    const float volts = adc_read() * 3.3f / (1 << 12);
    return 27.0f - (volts - 0.706f) / 0.001721f;  // formula from the RP2040 datasheet
}

struct Step { bool on; uint32_t ms; };
using Pattern = std::vector<Step>;

struct Mode {
    const char* name;
    Pattern pattern;
};

const char* morse_code(char c) {
    static const char* letters[] = {
        ".-", "-...", "-.-.", "-..", ".", "..-.", "--.", "....", "..", ".---", "-.-", ".-..", "--",
        "-.", "---", ".--.", "--.-", ".-.", "...", "-", "..-", "...-", ".--", "-..-", "-.--", "--.."};
    static const char* digits[] = {
        "-----", ".----", "..---", "...--", "....-", ".....", "-....", "--...", "---..", "----."};
    if (isalpha(c)) return letters[toupper(c) - 'A'];
    if (isdigit(c)) return digits[c - '0'];
    return nullptr;
}

// Standard Morse timing: dot = 1 unit, dash = 3, gap inside a letter = 1,
// between letters = 3, between words = 7.
Pattern morse(const char* text, uint32_t unit_ms = 150) {
    Pattern p;
    for (const char* c = text; *c; ++c) {
        if (*c == ' ') { p.push_back({false, 4 * unit_ms}); continue; }
        const char* code = morse_code(*c);
        if (!code) continue;
        for (const char* s = code; *s; ++s) {
            p.push_back({true, (*s == '-' ? 3u : 1u) * unit_ms});
            p.push_back({false, unit_ms});
        }
        p.back().ms = 3 * unit_ms;
    }
    p.push_back({false, 4 * unit_ms});  // word gap before the message repeats
    return p;
}

// True when the USB cable is supplying power (VBUS present), false on external power
bool usb_power_present() {
#if defined(PICO_VBUS_PIN)
    static bool ready = false;
    if (!ready) {
        gpio_init(PICO_VBUS_PIN);
        gpio_set_dir(PICO_VBUS_PIN, GPIO_IN);
        ready = true;
    }
    return gpio_get(PICO_VBUS_PIN);
#elif defined(CYW43_WL_GPIO_VBUS_PIN)
    return cyw43_arch_gpio_get(CYW43_WL_GPIO_VBUS_PIN);
#else
    return true;
#endif
}

int main() {
    stdio_init_all();

    Led led;
    if (!led.init()) return -1;

    adc_init();
    adc_set_temp_sensor_enabled(true);
    adc_select_input(NUM_ADC_CHANNELS - 1);  // the last channel is the internal temperature sensor

    for (int i = 0; i < 6; ++i) { led.toggle(); sleep_ms(60); }  // "I'm alive" blink

    // On USB power, give a serial monitor up to 3 s to connect so the banner isn't lost.
    // On battery there's no monitor coming, so don't wait.
    bool on_usb_power = usb_power_present();
    if (on_usb_power) {
        for (int i = 0; i < 30 && !stdio_usb_connected(); ++i) sleep_ms(100);
    }

    Console console(uart0, 0, 1);  // HC-06 Bluetooth: Pico TX = GP0, RX = GP1
    console.init();

    // The GPS (0x10) and IMU (0x4A) share I2C0. Both breakouts have their own pull-ups;
    // the internal ones are just backup.
    i2c_init(i2c0, 400 * 1000);
    gpio_set_function(PICO_DEFAULT_I2C_SDA_PIN, GPIO_FUNC_I2C);
    gpio_set_function(PICO_DEFAULT_I2C_SCL_PIN, GPIO_FUNC_I2C);
    gpio_pull_up(PICO_DEFAULT_I2C_SDA_PIN);
    gpio_pull_up(PICO_DEFAULT_I2C_SCL_PIN);

    // List everything that answers on the bus, to help track down wiring problems
    char i2c_devices[96] = "";
    for (uint8_t addr = 0x08; addr < 0x78; ++addr) {
        uint8_t byte;
        if (i2c_read_timeout_us(i2c0, addr, &byte, 1, false, 5000) == 1) {
            size_t len = strlen(i2c_devices);
            snprintf(i2c_devices + len, sizeof(i2c_devices) - len, " 0x%02X", addr);
        }
    }

    Pa1010d gps(i2c0);
    bool gps_found = gps.init();
    Bno085 imu(i2c0);
    bool imu_found = imu.init();
    SdLogger logger(CSV_HEADER);

    char board_id[2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES + 1];
    pico_get_unique_board_id_string(board_id, sizeof(board_id));

    // Printed at boot and again whenever someone types 's' (a Bluetooth link usually
    // connects after boot, so it would otherwise never see this)
    auto print_info = [&]() {
        console.print_all("\n=== Group 8 Pico 2 self-test ===\n");
        console.print_all("Board ID : %s\n", board_id);
        console.print_all("CPU clock: %lu MHz\n", (unsigned long)(clock_get_hz(clk_sys) / 1000000));
        console.print_all("Power    : %s\n", usb_power_present() ? "USB" : "external (no USB)");
        console.print_all("I2C bus  :%s\n", i2c_devices[0] ? i2c_devices : " nothing found");
        console.print_all("GPS      : %s\n", gps_found ? "PA1010D found at 0x10"
                                                       : "NOT FOUND - check wiring (SDA=GP4, SCL=GP5, 3V3, GND)");
        if (imu_found) console.print_all("IMU      : BNO085 found at 0x%02X\n", imu.address());
        else console.print_all("IMU      : NOT FOUND - check wiring (SDA=GP4, SCL=GP5, 3V3, GND)\n");
        if (logger.logging()) console.print_all("SD card  : logging to %s\n", logger.filename());
        else if (logger.card_present()) console.print_all("SD card  : card inserted, starting log\n");
        else console.print_all("SD card  : NO CARD INSERTED - data will not be saved\n");
        console.print_all("Output   : %s\n", Console::route_name(console.route()));
        console.print_all("Type u = USB only, b = Bluetooth only, a = both, s = show this again\n");
        console.print_all("Press BOOTSEL to change LED pattern\n\n");
    };
    print_info();

    const Mode modes[] = {
        {"Heartbeat",      {{true, 80}, {false, 120}, {true, 80}, {false, 720}}},
        {"Morse: GROUP 8", morse("GROUP 8")},
        {"Strobe",         {{true, 30}, {false, 70}}},
    };
    const size_t mode_count = sizeof(modes) / sizeof(modes[0]);

    // Overrides the chosen pattern whenever nothing is being saved: three quick flashes, then a pause
    const Pattern not_logging = {{true, 50}, {false, 100}, {true, 50}, {false, 100},
                                 {true, 50}, {false, 1000}};
    bool showing_not_logging = false;

    size_t mode = 0, step = 0;
    bool was_pressed = false;
    absolute_time_t step_end = get_absolute_time();
    absolute_time_t next_report = get_absolute_time();
    absolute_time_t next_log = get_absolute_time();

    while (true) {
        bool pressed = bootsel_pressed();
        if (pressed && !was_pressed) {
            mode = (mode + 1) % mode_count;
            step = 0;
            step_end = get_absolute_time();
            console.print(">> Mode: %s\n", modes[mode].name);
        }
        was_pressed = pressed;

        for (int c; (c = console.read_char()) >= 0;) {
            Console::Route route;
            switch (tolower(c)) {
                case 'u': route = Console::Route::Usb; break;
                case 'b': route = Console::Route::Bluetooth; break;
                case 'a': route = Console::Route::Both; break;
                case 's': print_info(); continue;
                default:  continue;  // ignore newlines and anything else
            }
            console.set_route(route);
            console.print_all(">> Output: %s\n", Console::route_name(route));
        }

        if (showing_not_logging != !logger.logging()) {
            showing_not_logging = !logger.logging();
            step = 0;  // the patterns are different lengths, so start the new one from the top
            step_end = get_absolute_time();
        }

        if (time_reached(step_end)) {
            const Pattern& pattern = showing_not_logging ? not_logging : modes[mode].pattern;
            led.set(pattern[step].on);
            step_end = make_timeout_time_ms(pattern[step].ms);
            step = (step + 1) % pattern.size();
        }

        if (time_reached(next_report)) {
            uint32_t uptime_s = to_ms_since_boot(get_absolute_time()) / 1000;
            char sd_status[48];
            if (logger.logging())
                snprintf(sd_status, sizeof(sd_status), "%s (%lu rows)", logger.filename(),
                         (unsigned long)logger.rows());
            else
                snprintf(sd_status, sizeof(sd_status), "not logging");
            console.print("[%4lus] temp %.1f C | mode %s | SD %s\n",
                          (unsigned long)uptime_s, chip_temp_c(), modes[mode].name, sd_status);

            if (gps_found) {
                const GpsFix& f = gps.fix();
                if (f.valid) {
                    console.print("        GPS %02u:%02u:%02u UTC | %.6f, %.6f | alt %.1f m | %u/%u sats | %.1f kn\n",
                           f.hour, f.minute, f.second, f.latitude, f.longitude,
                           f.altitude_m, f.satellites, f.satellites_in_view, f.speed_knots);
                } else {
                    console.print("        GPS searching... (%u sats in view, need ~4 for a fix)\n",
                                  f.satellites_in_view);
                }
            }
            if (imu_found) {
                const ImuData& d = imu.data();
                static const char* accuracy_names[] = {"unreliable", "low", "medium", "high"};
                console.print("        IMU yaw %6.1f pitch %6.1f roll %6.1f deg (%s) | accel %5.2f %5.2f %5.2f m/s^2\n",
                              d.yaw, d.pitch, d.roll, accuracy_names[d.accuracy],
                              d.accel[0], d.accel[1], d.accel[2]);
            }
            next_report = make_timeout_time_ms(1000);
        }

        if (gps_found) gps.poll();
        if (imu_found) imu.poll();

        // Once the GPS knows the date, start the clock so files on the card get real timestamps
        if (gps_found && gps.fix().valid && gps.fix().year >= 2024 && !aon_timer_is_running()) {
            const GpsFix& f = gps.fix();
            struct tm t = {};
            t.tm_year = f.year - 1900;
            t.tm_mon = f.month - 1;
            t.tm_mday = f.day;
            t.tm_hour = f.hour;
            t.tm_min = f.minute;
            t.tm_sec = f.second;
            struct timespec ts = {mktime(&t), 0};  // TZ isn't set, so this is UTC
            aon_timer_start(&ts);
        }

        switch (logger.update()) {
            case SdLogger::Event::Started:
                console.print_all(">> SD card: logging to %s\n", logger.filename());
                break;
            case SdLogger::Event::Removed:
                console.print_all(">> SD card: removed, stopped logging\n");
                break;
            case SdLogger::Event::Failed:
                console.print_all(">> SD card: can't start logging (%s)\n", logger.error());
                break;
            default:
                break;
        }

        if (logger.logging() && time_reached(next_log)) {
            char row[320];
            csv_row(row, sizeof(row), to_ms_since_boot(get_absolute_time()),
                    gps_found ? &gps.fix() : nullptr, imu_found ? &imu.data() : nullptr,
                    chip_temp_c());
            logger.write(row);
            next_log = delayed_by_ms(next_log, LOG_INTERVAL_MS);
            if (time_reached(next_log)) next_log = make_timeout_time_ms(LOG_INTERVAL_MS);  // fell behind
        }

        sleep_ms(20);  // also debounces the button
    }
}
