#ifndef SAILDROID_NATIVE_DISPLAY_EVENTS_H
#define SAILDROID_NATIVE_DISPLAY_EVENTS_H

#include <stdint.h>

int sd_window_display_available(void);
void sd_window_request_display_frame(void);
void sd_native_display_frame(int64_t timestamp);

#endif
