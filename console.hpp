// Text link to the laptop over USB, Bluetooth (an HC-06 on a UART), or both.
// Commands are read from both links no matter which one output is going to,
// so you can always switch back.
// One link at a time can also carry a machine-readable data stream for the desktop GUI;
// while it does, the human-readable status lines skip that link.
#pragma once
#include <cstdarg>
#include "hardware/uart.h"

class Console {
public:
    enum class Route { Usb, Bluetooth, Both };

    // tx_pin goes to the HC-06 RXD, rx_pin comes from the HC-06 TXD
    Console(uart_inst_t* bt_uart, uint tx_pin, uint rx_pin)
        : uart_(bt_uart), tx_(tx_pin), rx_(rx_pin) {}

    void init(uint bt_baud = 9600);  // the HC-06 ships set to 9600 baud

    // printf to whichever link(s) are selected, skipping the one carrying the data stream
    void print(const char* fmt, ...) __attribute__((format(printf, 2, 3)));
    // printf to both links, for things everyone should see (banner, route changes)
    void print_all(const char* fmt, ...) __attribute__((format(printf, 2, 3)));
    // printf to the data-stream link only (does nothing if no stream is running)
    void print_data(const char* fmt, ...) __attribute__((format(printf, 2, 3)));

    // Next character typed on either link, or -1 if nothing is waiting.
    // If from is given, it's set to the link the character came in on.
    int read_char(Route* from = nullptr);

    Route route() const { return route_; }
    void set_route(Route r) { route_ = r; }
    static const char* route_name(Route r);

    void start_stream(Route link) { streaming_ = true; stream_link_ = link; }
    void stop_stream() { streaming_ = false; }
    bool streaming() const { return streaming_; }
    Route stream_link() const { return stream_link_; }

private:
    void vprint(Route r, const char* fmt, va_list args);

    uart_inst_t* uart_;
    uint tx_, rx_;
    Route route_ = Route::Both;
    bool streaming_ = false;
    Route stream_link_ = Route::Usb;
};
