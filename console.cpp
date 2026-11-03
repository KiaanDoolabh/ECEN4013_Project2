#include "console.hpp"
#include <cstdio>
#include "pico/stdlib.h"
#include "pico/stdio_usb.h"

void Console::init(uint bt_baud) {
    uart_init(uart_, bt_baud);
    gpio_set_function(tx_, UART_FUNCSEL_NUM(uart_, tx_));
    gpio_set_function(rx_, UART_FUNCSEL_NUM(uart_, rx_));
    uart_set_format(uart_, 8, 1, UART_PARITY_NONE);
    uart_set_translate_crlf(uart_, true);  // terminals expect "\r\n" line endings
}

void Console::vprint(Route r, const char* fmt, va_list args) {
    char buf[256];
    vsnprintf(buf, sizeof(buf), fmt, args);
    // "USB only" with nobody on USB (e.g. running on battery) would go nowhere, so use Bluetooth
    if (r == Route::Usb && !stdio_usb_connected()) r = Route::Bluetooth;
    if (r != Route::Bluetooth) fputs(buf, stdout);  // stdio only goes to USB
    if (r != Route::Usb) uart_puts(uart_, buf);
}

void Console::print(const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vprint(route_, fmt, args);
    va_end(args);
}

void Console::print_all(const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vprint(Route::Both, fmt, args);
    va_end(args);
}

int Console::read_char() {
    int c = getchar_timeout_us(0);
    if (c != PICO_ERROR_TIMEOUT) return c;
    if (uart_is_readable(uart_)) return uart_getc(uart_);
    return -1;
}

const char* Console::route_name(Route r) {
    switch (r) {
        case Route::Usb:       return "USB (wired)";
        case Route::Bluetooth: return "Bluetooth (wireless)";
        default:               return "USB + Bluetooth";
    }
}
