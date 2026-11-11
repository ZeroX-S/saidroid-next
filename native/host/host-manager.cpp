#include "host-common.hpp"
#include <deque>
#include <map>
static fs::path component;
static GDBusConnection *connection;
struct Entry {
  Json record;
  std::string sender;
  bool heavy = false;
  int lease = -1;
  bool cleaned = false;
};
static std::map<std::string, Entry> entries;
static std::deque<std::string> heavy_queue;
static std::string latest_activation;
static uint64_t activation_serial;
static int acquire_lease(const std::string &key) {
  int fd = open((runtime_dir() / (key + ".lock")).c_str(),
                O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
  if (fd < 0)
    throw std::runtime_error("Host lock unavailable");
  struct flock value{};
  value.l_type = F_WRLCK;
  value.l_whence = SEEK_SET;
  if (fcntl(fd, F_SETLK, &value)) {
    close(fd);
    throw std::runtime_error("Application update or uninstall is active");
  }
  return fd;
}
static const char xml[] = R"(<node><interface name='org.saildroid.HostManager1'>
 <method name='RegisterHost'><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='b' direction='out'/><arg type='s' direction='out'/></method>
 <method name='GetState'><arg type='s' direction='in'/><arg type='s' direction='out'/></method>
 <method name='WindowEvent'><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='i' direction='in'/></method>
 <method name='SetState'><arg type='s' direction='in'/><arg type='s' direction='in'/></method>
 <method name='TryAcquireHeavy'><arg type='s' direction='in'/><arg type='b' direction='out'/></method>
 <method name='ReleaseHeavy'><arg type='s' direction='in'/></method>
 <method name='EnsureBroker'/>
 <method name='OpenApplication'><arg type='s' direction='in'/></method>
 <method name='StartService'><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='s' direction='in'/></method>
 <method name='StartActivityProcess'><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='s' direction='in'/></method>
 <method name='StartProviderProcess'><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='s' direction='in'/></method>
 <method name='Activate'><arg type='s' direction='in'/><arg type='s' direction='in'/></method>
 <method name='ActivateApplication'><arg type='s' direction='in'/><arg type='s' direction='in'/></method>
 <method name='Close'><arg type='s' direction='in'/><arg type='s' direction='in'/></method>
 </interface></node>)";
static unsigned credential(const char *sender, const char *method) {
  GError *e = nullptr;
  auto v = g_dbus_connection_call_sync(
      connection, "org.freedesktop.DBus", "/org/freedesktop/DBus",
      "org.freedesktop.DBus", method, g_variant_new("(s)", sender),
      G_VARIANT_TYPE("(u)"), G_DBUS_CALL_FLAGS_NONE, 2000, nullptr, &e);
  if (!v) {
    g_clear_error(&e);
    throw std::runtime_error("Caller credentials unavailable");
  }
  unsigned n;
  g_variant_get(v, "(u)", &n);
  g_variant_unref(v);
  return n;
}
static void publish(const std::string &key) {
  save_json(runtime_dir() / (key + ".json"), entries.at(key).record);
}
static bool valid_package(const std::string &s) {
  return std::regex_match(
      s, std::regex("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)+"));
}
static void launch(std::vector<std::string> args) {
  std::vector<char *> av;
  std::string exe = (component / "libexec/saildroid-app").string();
  av.push_back(exe.data());
  for (auto &s : args)
    av.push_back(s.data());
  av.push_back(nullptr);
  GError *e = nullptr;
  if (!g_spawn_async(nullptr, av.data(), nullptr, G_SPAWN_DEFAULT, nullptr,
                     nullptr, nullptr, &e)) {
    std::string s = e->message;
    g_clear_error(&e);
    throw std::runtime_error(s);
  }
}
struct RetiringFamily {
  Json owner;
  gint64 deadline;
};
static std::vector<RetiringFamily> retiring;
static void reap_helpers() {
  for (auto it = retiring.begin(); it != retiring.end();) {
    const auto &r = it->owner;
    pid_t group = r.at("pid");
    bool reused = false;
    try {
      if (fs::exists("/proc/" + std::to_string(group)) &&
          start_ticks(group) != r.at("start_ticks").get<uint64_t>())
        reused = true;
    } catch (...) {
      reused = true;
    }
    bool members = false;
    if (!reused)
      for (auto &path : fs::directory_iterator("/proc")) {
        std::string name = path.path().filename();
        if (name.empty() || name.find_first_not_of("0123456789") != name.npos)
          continue;
        pid_t pid = std::stoi(name);
        if (pid == group || getpgid(pid) != group)
          continue;
        try {
          Json child{{"pid", pid},
                     {"start_ticks", start_ticks(pid)},
                     {"boot", boot_id()}};
          if (!alive(child) || getpgid(pid) != group)
            continue;
          members = true;
          // Signal only a freshly verified member of this exact retired
          // session.
          if (alive(child) && getpgid(pid) == group)
            kill(pid,
                 g_get_monotonic_time() < it->deadline ? SIGTERM : SIGKILL);
        } catch (...) {
        }
      }
    if (reused || !members)
      it = retiring.erase(it);
    else
      ++it;
  }
}
static gboolean monitor(gpointer) {
  try {
    for (auto &[key, value] : entries) {
      auto &r = value.record;
      if (alive(r) || value.cleaned)
        continue;
      value.cleaned = true;
      value.heavy = false;
      if (value.lease >= 0) {
        close(value.lease);
        value.lease = -1;
      }
      heavy_queue.erase(
          std::remove(heavy_queue.begin(), heavy_queue.end(), key),
          heavy_queue.end());
      r["state"] = "exited";
      r["exit_reason"] = "process-ended";
      r["exit_code"] = nullptr;
      publish(key);
      retiring.push_back({r, g_get_monotonic_time() + 3000000});
      for (auto field : {"socket", "ready_file"})
        if (r.contains(field) && r.at(field).is_string()) {
          fs::path path = r.at(field).get<std::string>();
          struct stat info;
          if (path.parent_path() == runtime_dir() &&
              !lstat(path.c_str(), &info) && info.st_uid == getuid() &&
              ((std::string(field) == "socket" && S_ISSOCK(info.st_mode)) ||
               (std::string(field) == "ready_file" && S_ISREG(info.st_mode))))
            unlink(path.c_str());
        }
      if (r.value("role", "") == "activity")
        for (auto &[child, service] : entries)
          if (service.record.value("role", "") == "service" &&
              service.record.value("owner_launch_id", "") ==
                  r.value("launch_id", ""))
            signal_owned(service.record, SIGTERM);
    }
    reap_helpers();
  } catch (const std::exception &e) {
    std::cerr << "SDHOST_MANAGER=monitor_error|" << e.what() << '\n';
  }
  return G_SOURCE_CONTINUE;
}
static void dispatch(GDBusConnection *, const gchar *sender, const gchar *,
                     const gchar *, const gchar *method, GVariant *params,
                     GDBusMethodInvocation *reply, gpointer) {
  try {
    if (credential(sender, "GetConnectionUnixUser") != getuid())
      throw std::runtime_error("Caller UID differs");
    pid_t pid = credential(sender, "GetConnectionUnixProcessID");
    const char *a = "", *b = "", *c = "";
    std::string m = method;
    Json out;
    if (m == "RegisterHost") {
      g_variant_get(params, "(&s&s)", &a, &b);
      std::string key = a;
      Json r = Json::parse(b);
      std::string package = r.at("package"), role = r.at("role");
      if (!valid_package(package) || key.find('/') != key.npos ||
          key.size() > 200)
        throw std::runtime_error("Invalid host identity");
      if (fs::canonical("/proc/" + std::to_string(pid) + "/exe") !=
          component / "libexec/saildroid-host")
        throw std::runtime_error("Host executable differs");
      // A new launch can beat the 250ms monitor after its predecessor exits.
      // Retire that generation, including its services, before overwriting the
      // per-package entry with the new lease.
      if (entries.count(key) && !alive(entries[key].record))
        monitor(nullptr);
      if (entries.count(key) && alive(entries[key].record)) {
        if (entries[key].record.at("pid") == pid) {
          entries[key].sender = sender;
          std::string same = entries[key].record.dump();
          g_dbus_method_invocation_return_value(
              reply, g_variant_new("(bs)", true, same.c_str()));
          return;
        }
        if (role == "activity") {
          latest_activation = key;
          entries[key].record["activation_serial"] = ++activation_serial;
          publish(key);
        }
        std::string existing = entries[key].record.dump();
        g_dbus_method_invocation_return_value(
            reply, g_variant_new("(bs)", false, existing.c_str()));
        return;
      }
      if (role == "service") {
        std::string owner = package;
        if (!entries.count(owner) || !alive(entries[owner].record) ||
            entries[owner].record.value("launch_id", "") !=
                r.value("owner_launch_id", ""))
          throw std::runtime_error("Service owner ended");
        if (r.at("component") != entries[owner].record.at("component"))
          throw std::runtime_error("Service component differs");
      }
      r["pid"] = pid;
      r["start_ticks"] = start_ticks(pid);
      r["boot"] = boot_id();
      r["schema"] = 3;
      r["state"] = "starting";
      r["supervisor_pid"] = nullptr;
      r["process_group"] = pid;
      if (entries.count(key) && entries[key].lease >= 0) {
        close(entries[key].lease);
        entries[key].lease = -1;
      }
      int lease = acquire_lease(key);
      if (r.contains("app_record_sha256")) {
        try {
          if (sha(read_text(fs::path("/home/art/apps") / package /
                            "record.json")) !=
              r.at("app_record_sha256").get<std::string>())
            throw std::runtime_error(
                "Application installation changed during launch");
        } catch (...) {
          close(lease);
          throw;
        }
      }
      if (role == "activity") {
        latest_activation = key;
        r["activation_serial"] = ++activation_serial;
      }
      entries[key] = {r, sender, false, lease, false};
      publish(key);
      std::string result = r.dump();
      g_dbus_method_invocation_return_value(
          reply, g_variant_new("(bs)", true, result.c_str()));
      return;
    }
    if (m == "EnsureBroker") {
      auto it = entries.find("org.saildroid.binder");
      bool exists = it != entries.end() && alive(it->second.record);
      static gint64 started = 0;
      if (!exists && g_get_monotonic_time() - started > 2000000) {
        started = g_get_monotonic_time();
        launch({"--broker"});
      }
    } else if (m == "OpenApplication") {
      g_variant_get(params, "(&s)", &a);
      if (!valid_package(a) || std::string(a).rfind("org.saildroid.", 0) == 0)
        throw std::runtime_error("Invalid application");
      launch({"--package", a});
    } else if (m == "StartService" || m == "StartActivityProcess" || m == "StartProviderProcess") {
      g_variant_get(params, "(&s&s&s)", &a, &b, &c);
      if (!valid_package(a) || !valid_component(b) ||
          !std::regex_match(c, std::regex("[A-Za-z0-9_.]+(:[A-Za-z0-9_.]+)?")))
        throw std::runtime_error("Invalid service identity");
      auto it = entries.find(a);
      if (it == entries.end() || !alive(it->second.record))
        throw std::runtime_error("Service application owner ended");
      bool caller = it->second.record.at("pid") == pid;
      for (auto &[key, entry] : entries)
        if (alive(entry.record) && entry.record.at("pid") == pid &&
            entry.record.value("package", "") == a &&
            entry.record.value("owner_launch_id", "") ==
                it->second.record.value("launch_id", ""))
          caller = true;
      if (!caller)
        throw std::runtime_error(
            "Service caller differs from application family");
      launch({"--package", a, m == "StartService" ? "--service" : m == "StartActivityProcess" ? "--activity-process" : "--provider-process", b, "--process", c, "--owner-launch",
              it->second.record.at("launch_id"), "--component",
              it->second.record.at("component")});
    } else {
      int number = 0;
      if (m == "WindowEvent")
        g_variant_get(params, "(&s&si)", &a, &b, &number);
      else if (m == "SetState" || m == "Close" || m == "Activate" || m == "ActivateApplication")
        g_variant_get(params, "(&s&s)", &a, &b);
      else
        g_variant_get(params, "(&s)", &a);
      auto it = entries.find(a);
      if (m == "GetState") {
        Json record = it == entries.end() ? Json::object() : it->second.record;
        record["running"] = alive(record);
        std::string result = record.dump();
        g_dbus_method_invocation_return_value(
            reply, g_variant_new("(s)", result.c_str()));
        return;
      }
      if (it == entries.end() || !alive(it->second.record))
        throw std::runtime_error("Host no longer exists");
      auto &host = it->second;
      if ((m == "Close" || m == "Activate" || m == "ActivateApplication") &&
          host.record.value("launch_id", "") != b)
        throw std::runtime_error("Host generation differs");
      if (m == "ActivateApplication") {
        auto selected=it;
        uint64_t serial=0;
        for(auto child=entries.begin();child!=entries.end();++child){
          const auto &r=child->second.record;
          if(r.value("role","")=="service" &&
             r.value("package","")==host.record.value("package","") &&
             r.value("owner_launch_id","")==host.record.value("launch_id","") &&
             r.value("window_mapped",false) && !r.value("close_requested",false) &&
             alive(r) && r.value("activation_serial",uint64_t(0))>=serial){
            selected=child;serial=r.value("activation_serial",uint64_t(0));
          }
        }
        latest_activation=selected->first;
        selected->second.record["activation_serial"]=++activation_serial;
        publish(selected->first);control(selected->second.record,"activate");
      } else if (m == "Activate") {
        latest_activation = a;
        host.record["activation_serial"] = ++activation_serial;
        publish(a);
        control(host.record, "activate");
      } else if (m == "Close") {
        host.record["close_requested"] = true;
        host.record["state"] = "closing";
        publish(a);
        try {
          control(host.record, "close");
        } catch (...) {
          signal_owned(host.record, SIGTERM);
        }
      } else {
        if (host.record.at("pid") != pid ||
            (host.sender != sender && !host.sender.empty()))
          throw std::runtime_error("Host lease differs");
        if (host.sender.empty())
          host.sender = sender;
        if (m == "WindowEvent") {
          std::string event = b;
          if (event == "focus")
            host.record["focused"] = number != 0;
          else if (event == "visibility")
            host.record["visibility"] = number;
          else if (event == "first-frame")
            host.record["first_frame_seen"] = true;
          else if (event == "mapped") {
            host.record["window_mapped"] = true;
            auto selected = entries.find(latest_activation);
            if (host.record.value("role", "") == "service" &&
                selected != entries.end() &&
                selected->second.record.value("package", "") ==
                    host.record.value("package", "") &&
                (selected->second.record.value("launch_id", "") ==
                     host.record.value("owner_launch_id", "") ||
                 selected->second.record.value("owner_launch_id", "") ==
                     host.record.value("owner_launch_id", ""))) {
              latest_activation = a;
              host.record["activation_serial"] = ++activation_serial;
            }
            if (latest_activation != a && entries.count(latest_activation) &&
                alive(entries[latest_activation].record))
              try {
                control(entries[latest_activation].record, "activate");
              } catch (...) {
              }
          } else
            throw std::runtime_error("Invalid window event");
          publish(a);
        } else if (m == "SetState") {
          std::string s = b;
          if (s != "window-ready" && s != "art-starting" &&
              s != "art-running" && s != "closing" && s != "exited")
            throw std::runtime_error("Invalid lifecycle state");
          host.record["state"] = s;
          publish(a);
        } else if (m == "TryAcquireHeavy") {
          std::string key = a;
          if (std::find(heavy_queue.begin(), heavy_queue.end(), key) ==
                  heavy_queue.end() &&
              !host.heavy)
            heavy_queue.push_back(key);
          bool free = true;
          for (auto &[k, e] : entries)
            if (k != a && e.heavy && alive(e.record))
              free = false;
          if (!heavy_queue.empty() && heavy_queue.front() != key && !host.heavy)
            free = false;
          if (free) {
            host.heavy = true;
            if (!heavy_queue.empty() && heavy_queue.front() == key)
              heavy_queue.pop_front();
          }
          g_dbus_method_invocation_return_value(reply,
                                                g_variant_new("(b)", free));
          return;
        } else if (m == "ReleaseHeavy")
          host.heavy = false;
        else
          throw std::runtime_error("Unknown method");
      }
    }
    g_dbus_method_invocation_return_value(reply, nullptr);
  } catch (const std::exception &e) {
    g_dbus_method_invocation_return_dbus_error(reply, "org.saildroid.Error",
                                               e.what());
  }
}
int sd_manager_main(const fs::path &root) {
  component = root;
  GError *e = nullptr;
  connection = g_bus_get_sync(G_BUS_TYPE_SESSION, nullptr, &e);
  if (!connection)
    throw std::runtime_error(e ? e->message : "Session bus unavailable");
  auto result = g_dbus_connection_call_sync(
      connection, "org.freedesktop.DBus", "/org/freedesktop/DBus",
      "org.freedesktop.DBus", "RequestName", g_variant_new("(su)", BUS, 4u),
      G_VARIANT_TYPE("(u)"), G_DBUS_CALL_FLAGS_NONE, 3000, nullptr, &e);
  if (!result)
    throw std::runtime_error("Manager name request failed");
  unsigned owned;
  g_variant_get(result, "(u)", &owned);
  g_variant_unref(result);
  if (owned != 1)
    return 0;
  auto info = g_dbus_node_info_new_for_xml(xml, &e);
  static const GDBusInterfaceVTable vtable = {
      dispatch, nullptr, nullptr, {nullptr}};
  if (!g_dbus_connection_register_object(connection, OBJECT,
                                         info->interfaces[0], &vtable, nullptr,
                                         nullptr, &e))
    throw std::runtime_error("Manager registration failed");
  save_json(runtime_dir() / "host-manager.state",
            Json{{"pid", getpid()},
                 {"start_ticks", start_ticks(getpid())},
                 {"boot", boot_id()},
                 {"component", component.string()},
                 {"role", "session"}});
  // Re-adopt only matching host identities from this component after a manager
  // restart.
  for (auto &p : fs::directory_iterator(runtime_dir()))
    if (p.path().extension() == ".json")
      try {
        auto r = read_json(p.path());
        if (r.value("schema", 0) == 3 &&
            r.value("component", "") == component && alive(r)) {
          auto key = p.path().stem().string();
          entries[key] = {r, "", false, acquire_lease(key), false};
        }
      } catch (...) {
      }
  g_timeout_add(250, monitor, nullptr);
  std::cerr << "SDHOST_MANAGER=ready|pid=" << getpid() << '\n';
  g_main_loop_run(g_main_loop_new(nullptr, false));
  return 0;
}
