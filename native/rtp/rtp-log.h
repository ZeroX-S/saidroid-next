#pragma once
#include <cstdio>
#define ALOGE(...) do { std::fprintf(stderr, "SDRTP=error|"); std::fprintf(stderr, __VA_ARGS__); std::fputc('\n', stderr); } while (0)
#define ALOGW(...) ALOGE(__VA_ARGS__)
#define ALOGD(...) do { std::fprintf(stderr, "SDRTP="); std::fprintf(stderr, __VA_ARGS__); std::fputc('\n', stderr); } while (0)
#define ALOGV(...) do { } while (0)
