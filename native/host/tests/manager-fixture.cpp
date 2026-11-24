/* Test-only process client; never packaged into the phone component. */
#include "../host-common.hpp"
#include <condition_variable>
#include <mutex>
int sd_manager_main(const fs::path &);
int main(int argc, char **argv) {
  try {
    auto root = fs::canonical("/proc/self/exe").parent_path().parent_path();
    if (argc > 1 && std::string(argv[1]) == "--session")
      return sd_manager_main(root);
    if (setsid() < 0 && getpgrp() != getpid())
      throw std::runtime_error("Fixture session unavailable");
    GError *error = nullptr;
    auto bus = g_bus_get_sync(G_BUS_TYPE_SESSION, nullptr, &error);
    if (!bus)
      throw std::runtime_error("No test bus");
    struct SignalTracker {
      std::mutex m;
      std::condition_variable cv;
      uint64_t count = 0;
    } tracker;
    g_dbus_connection_add_filter(
        bus,
        +[](GDBusConnection *, GDBusMessage *msg, gboolean incoming,
            gpointer data) -> GDBusMessage * {
          if (incoming &&
              g_dbus_message_get_message_type(msg) ==
                  G_DBUS_MESSAGE_TYPE_SIGNAL &&
              g_strcmp0(g_dbus_message_get_interface(msg), IFACE) == 0 &&
              g_strcmp0(g_dbus_message_get_member(msg), "StateChanged") == 0) {
            auto *t = static_cast<SignalTracker *>(data);
            std::lock_guard<std::mutex> lock(t->m);
            ++t->count;
            t->cv.notify_all();
          }
          return msg;
        },
        &tracker, nullptr);
    if (auto mr = g_dbus_connection_call_sync(
            bus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "AddMatch",
            g_variant_new("(s)", "type='signal',interface='org.saildroid.HostManager1',member='StateChanged',path='/org/saildroid/HostManager'"),
            nullptr, G_DBUS_CALL_FLAGS_NONE, 1000, nullptr, nullptr))
      g_variant_unref(mr);
    std::string key = argv[1], role = argc > 2 ? argv[2] : "activity",
                owner = argc > 3 ? argv[3] : "";
    std::string package = role == "service" ? "org.example.a" : key;
    Json record = {
        {"package", package},
        {"role", role},
        {"launch_id", nonce()},
        {"owner_launch_id", owner},
        {"component", root.string()},
        {"socket",
         (runtime_dir() / ("fixture-" + nonce() + ".sock")).string()}};
    auto v = call(bus, "RegisterHost",
                  g_variant_new("(ss)", key.c_str(), record.dump().c_str()));
    gboolean accepted;
    const char *text;
    g_variant_get(v, "(b&s)", &accepted, &text);
    Json returned = Json::parse(text);
    returned["accepted"] = bool(accepted);
    std::cout << returned.dump() << std::endl;
    g_variant_unref(v);
    if (!accepted)
      return 0;
    std::string line;
    while (std::getline(std::cin, line)) {
      try {
        std::istringstream in(line);
        std::string method, arg;
        in >> method >> arg;
        if (method == "exit")
          return 0;
        if (method == "SignalCount") {
          std::lock_guard<std::mutex> lock(tracker.m);
          std::cout << Json{{"signals", tracker.count}}.dump() << std::endl;
          continue;
        }
        if (method == "WaitSignal") {
          uint64_t baseline = std::stoull(arg);
          std::unique_lock<std::mutex> lock(tracker.m);
          bool woke = tracker.cv.wait_for(
              lock, std::chrono::milliseconds(1500),
              [&] { return tracker.count > baseline; });
          std::cout << Json{{"woke", woke}, {"signals", tracker.count}}.dump()
                    << std::endl;
          continue;
        }
        if (method == "SpawnHelper") {
          pid_t child = fork();
          if (child < 0)
            throw std::runtime_error("Fixture fork failed");
          if (!child) {
            close(0);
            close(1);
            close(2);
            for (;;)
              pause();
          }
          std::cout << Json{{"helper_pid", child}}.dump() << std::endl;
          continue;
        }
        if (method == "TryAcquireHeavy" || method == "ReleaseHeavy" ||
            method == "GetState")
          v = call(bus, method.c_str(),
                   g_variant_new("(s)", (arg.empty() ? key : arg).c_str()));
        else if (method == "SetState" || method == "Close") {
          std::string value;
          in >> value;
          v = call(bus, method.c_str(),
                   g_variant_new("(ss)", arg.c_str(), value.c_str()));
        } else
          throw std::runtime_error("Unknown test method");
        gchar *printed = g_variant_print(v, true);
        std::cout << Json{{"reply", printed}}.dump() << std::endl;
        g_free(printed);
        g_variant_unref(v);
      } catch (const std::exception &e) {
        std::cout << Json{{"error", e.what()}}.dump() << std::endl;
      }
    }
    return 0;
  } catch (const std::exception &e) {
    std::cout << Json{{"error", e.what()}}.dump() << std::endl;
    return 1;
  }
}
