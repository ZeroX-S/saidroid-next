#include <cstdio>
#include <memory>
#include <stdexcept>

#ifndef HOST_AUDIO_SOURCE
#define HOST_AUDIO_SOURCE "../host-audio.cpp"
#endif
#include HOST_AUDIO_SOURCE

// The callback fixtures use real PulseAudio property lists with a local,
// unconnected context. They perform no server connection or route changes.
extern "C" int pa_context_connect(pa_context*, const char*, pa_context_flags_t, const pa_spawn_api*) {
    return 0;
}
extern "C" pa_context_state_t pa_context_get_state(const pa_context*) {
    return PA_CONTEXT_READY;
}
extern "C" void pa_context_disconnect(pa_context*) {}

namespace {
void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

struct RouteCase {
    const char *name;
    const char *api;
    const char *protocol;
    const char *profile;
    bool properties;
};
}

int main() {
    try {
        const RouteCase cases[] = {
            {"missing property list", nullptr, nullptr, nullptr, false},
            {"empty property list", nullptr, nullptr, nullptr, true},
            {"built-in output", "droid", nullptr, nullptr, true},
            {"BlueZ SCO", "bluez", "sco", nullptr, true},
            {"BlueZ A2DP", "bluez", "a2dp", nullptr, true},
            {"BlueZ5 HFP protocol", "bluez5", "handsfree_head_unit", nullptr, true},
            {"BlueZ5 HFP profile", "bluez5", nullptr, "handsfree-head-unit", true},
            {"BlueZ5 HSP profile", "bluez5", nullptr, "headset-head-unit", true},
            {"unknown Bluetooth profile", "bluez5", nullptr, nullptr, true},
            {"explicit empty properties", "", "", "", true},
        };
        Query query;
        query.default_sink = "default-output";
        pa_sink_info info{};
        info.index = 11;
        info.name = "default-output";
        info.description = "Fixture output";
        info.sample_spec = {PA_SAMPLE_S16LE, 48000, 2};
        pa_cvolume_set(&info.volume, 2, PA_VOLUME_NORM / 2);
        info.mute = 1;
        info.state = PA_SINK_RUNNING;
        for (const auto &test : cases) {
            std::unique_ptr<pa_proplist, decltype(&pa_proplist_free)> properties(pa_proplist_new(), pa_proplist_free);
            check(bool(properties), "PulseAudio property allocation failed");
            if (test.api) check(pa_proplist_sets(properties.get(), "device.api", test.api) == 0, "API property failed");
            if (test.protocol) check(pa_proplist_sets(properties.get(), "bluetooth.protocol", test.protocol) == 0, "Protocol property failed");
            if (test.profile) check(pa_proplist_sets(properties.get(), "api.bluez5.profile", test.profile) == 0, "Profile property failed");
            info.proplist = test.properties ? properties.get() : nullptr;
            query.result["outputs"] = Json::array();
            sink(nullptr, &info, 0, &query);
            const Json row = query.result.at("outputs").at(0);
            check(row.at("device_api") == (test.api ? test.api : ""), test.name);
            check(row.at("bluetooth_protocol") == (test.protocol ? test.protocol : ""), test.name);
            check(row.at("bluez5_profile") == (test.profile ? test.profile : ""), test.name);
            check(row.at("device_api").is_string() && row.at("bluetooth_protocol").is_string()
                  && row.at("bluez5_profile").is_string(), "Route property type changed");
        }
        const Json row = query.result.at("outputs").at(0);
        check(row.at("id") == 11 && row.at("name") == "default-output"
              && row.at("description") == "Fixture output" && row.at("rate") == 48000
              && row.at("channels") == 2 && row.at("volume") == 0.5
              && row.at("muted") == true && row.at("active") == true
              && row.at("default") == true && row.size() == 12,
              "Existing audio snapshot fields changed");
        sink(nullptr, nullptr, 0, &query);
        sink(nullptr, &info, 1, &query);
        sink(nullptr, &info, -1, &query);
        check(query.result.at("outputs").size() == 1, "End or null callback added a sink");
        std::puts("AUDIO_SINK_METADATA=PASS|cases=12");
        return 0;
    } catch (const std::exception &failure) {
        std::fprintf(stderr, "AUDIO_SINK_METADATA=FAIL|%s\n", failure.what());
        return 1;
    }
}
