#include "host-common.hpp"
#include "instrumentation-policy.hpp"
#include "app-filesystem-policy.hpp"
#include <dlfcn.h>
#include <linux/capability.h>
#include <pwd.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/syscall.h>
int sd_art_main(int, char **);
int sd_manager_main(const fs::path &);
static GDBusConnection *bus;
static std::string instance;
static bool registered;
static void state(const std::string &value) {
  auto v = call(bus, "SetState",
                g_variant_new("(ss)", instance.c_str(), value.c_str()));
  g_variant_unref(v);
}
extern "C" void sd_host_window_event(const char *event, int value) {
  if (!registered || !bus)
    return;
  g_dbus_connection_call(bus, BUS, OBJECT, IFACE, "WindowEvent",
                         g_variant_new("(ssi)", instance.c_str(), event, value),
                         nullptr, G_DBUS_CALL_FLAGS_NONE, 2000, nullptr,
                         nullptr, nullptr);
}
extern "C" void sd_host_java_ready() {
  if (!registered)
    return;
  try {
    state("art-running");
    std::cerr << "SDHOST=lifecycle_ready|pid=" << getpid()
              << "|key=" << instance << '\n';
    auto v = call(bus, "ReleaseHeavy", g_variant_new("(s)", instance.c_str()));
    g_variant_unref(v);
  } catch (const std::exception &e) {
    std::cerr << "SDHOST=lease_error|" << e.what() << '\n';
  }
}
extern "C" int sd_host_prepare_art() {
  if (!registered)
    return 0;
  try {
    state("window-ready");
    if (instance != "org.saildroid.binder") {
      auto v = call(bus, "EnsureBroker", nullptr);
      g_variant_unref(v);
      bool ready = false;
      for (int i = 0; i < 400; i++) {
        auto r =
            call(bus, "GetState", g_variant_new("(s)", "org.saildroid.binder"));
        const char *t;
        g_variant_get(r, "(&s)", &t);
        Json broker = Json::parse(t);
        g_variant_unref(r);
        try {
          if (alive(broker) &&
              read_text(broker.at("ready_file").get<std::string>()) ==
                  std::to_string(broker.at("pid").get<int>()) &&
              control(broker, "activate") == "requested\n") {
            ready = true;
            break;
          }
        } catch (...) {
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
      }
      if (!ready)
        throw std::runtime_error("Binder startup deadline expired");
      bool acquired = false;
      for (int i = 0; i < 600; i++) {
        auto r = call(bus, "TryAcquireHeavy",
                      g_variant_new("(s)", instance.c_str()));
        gboolean ok;
        g_variant_get(r, "(b)", &ok);
        g_variant_unref(r);
        if (ok) {
          acquired = true;
          break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
      }
      if (!acquired)
        throw std::runtime_error("ART startup admission deadline expired");
    }
    state("art-starting");
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "SDHOST=prepare_failed|" << e.what() << '\n';
    return 125;
  }
}
static void trusted(const fs::path &p) {
  struct stat s;
  if (lstat(p.c_str(), &s) || s.st_uid != 0 || (s.st_mode & 022) ||
      S_ISLNK(s.st_mode))
    throw std::runtime_error("Untrusted component path: " + p.string());
}
static fs::path own_root() {
  auto root = fs::canonical("/proc/self/exe").parent_path().parent_path();
  trusted(root);
  trusted(root / "runtime.json");
  if (read_json(root / "runtime.json").at("api") != 28)
    throw std::runtime_error("API28 required");
  return root;
}
static void permissions() {
  uid_t uid = getuid();
  if (!uid || geteuid() != uid)
    throw std::runtime_error("Run as ordinary phone user");
  rlimit lim{};
  getrlimit(RLIMIT_NICE, &lim);
  if (lim.rlim_cur < 40) {
    rlimit requested{40, 40};
    if (setrlimit(RLIMIT_NICE, &requested))
      throw std::runtime_error("Scheduling capability unavailable");
  }
  __user_cap_header_struct header{_LINUX_CAPABILITY_VERSION_3, 0};
  __user_cap_data_struct caps[2]{};
  if (syscall(SYS_capset, &header, caps) ||
      prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0))
    throw std::runtime_error("Cannot drop capabilities");
}
static void env(const char *key, const std::string &value) {
  if (setenv(key, value.c_str(), 1))
    throw std::runtime_error("Cannot set runtime environment");
}
static void environment(const fs::path &root) {
  auto account = getpwuid(getuid());
  if (!account)
    throw std::runtime_error("User account unavailable");
  env("HOME", account->pw_dir);
  env("USER", account->pw_name);
  env("LOGNAME", account->pw_name);
  env("ANDROID_ROOT", root);
  env("ANDROID_DATA", "/home/art/data");
  env("LD_LIBRARY_PATH", (root / "lib").string()+":/home/art/lib");
  env("ICU_DATA", root / "usr/icu");
  env("SD_BUILD_PROP", root / "build.prop");
  env("BIONIC_TRANSLATION_CONFIG_DIR", root / "linker-config");
  env("SAILDROID_STRICT_LINK", "1");
  // The Android linker resolves allocator/mapper hooks while loading libui.
  // Publish the component's gralloc wrappers before that first resolution.
  trusted(root / "lib/libsdtexture-host.so");
  std::string preload = (root / "lib/libsdtexture-host.so").string() + ":";
  if (fs::exists(root / "lib/libpthread_bio.so.0"))
    preload += (root / "lib/libpthread_bio.so.0").string() + ":";
  if (fs::exists(root / "lib/libsdstrictmath-fdlibm.so")) {
    trusted(root / "lib/libsdstrictmath-fdlibm.so");
    preload += (root / "lib/libsdstrictmath-fdlibm.so").string() + ":";
  }
  if (fs::exists(root / "lib/libsdcharacter-icu63.so")) {
    trusted(root / "lib/libsdcharacter-icu63.so");
    preload += (root / "lib/libsdcharacter-icu63.so").string() + ":";
  }
  preload += (root / "lib/libsdhost29.so").string() + ":" +
             (root / "lib/libdl_bio.so.0").string() + ":libresolv.so.2";
  env("LD_PRELOAD", preload);
  for (auto key : {"SAILDROID_HEADLESS", "SAILDROID_STARTUP_ICON",
                   "SAILDROID_CONTROL_SOCKET", "SAILDROID_APP_LAUNCH_ID",
                   "SAILDROID_PACKAGE", "SAILDROID_DATA_DIR", "SAILDROID_DESKTOP_ID"})
    unsetenv(key);
  env("SAILDROID_HWUI", "1");
  env("EGL_PLATFORM", "wayland");
  env("HYBRIS_EGLPLATFORM", "wayland");
  env("EXTERNAL_STORAGE", "/home/art/data/shared");
  env("XDG_RUNTIME_DIR", "/run/user/" + std::to_string(getuid()));
  env("WAYLAND_DISPLAY", "../../display/wayland-0");
}
static bool valid(const std::string &s) {
  return std::regex_match(
      s, std::regex("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)+"));
}
static Json app_record(const std::string &name) {
  if (!valid(name) || name == "android" || name.rfind("org.saildroid.", 0) == 0)
    throw std::runtime_error("Invalid installed application");
  fs::path app = "/home/art/apps/" + name;
  if (fs::is_symlink(app) ||
      fs::canonical(app).parent_path() != fs::canonical("/home/art/apps"))
    throw std::runtime_error("Application directory escaped");
  std::string raw_record = read_text(app / "record.json");
  Json r = Json::parse(raw_record);
  r["_record_sha256"] = sha(raw_record);
  if (r.at("package") != name)
    throw std::runtime_error("Application record differs");
  for (auto key : {"apk", "native", "icon", "data"}) {
    auto p = fs::canonical(r.at(key).get<std::string>());
    auto relative = p.lexically_relative(fs::canonical(app));
    if (relative.empty() || *relative.begin() == "..")
      throw std::runtime_error("Application path escaped");
  }
  return r;
}
static void connect_manager(const fs::path &root) {
  GError *e = nullptr;
  bus = g_bus_get_sync(G_BUS_TYPE_SESSION, nullptr, &e);
  if (!bus)
    throw std::runtime_error(e ? e->message : "No session bus");
  auto ping = [&]() {
    GError *error = nullptr;
    auto v = g_dbus_connection_call_sync(
        bus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
        "org.freedesktop.DBus", "NameHasOwner", g_variant_new("(s)", BUS),
        G_VARIANT_TYPE("(b)"), G_DBUS_CALL_FLAGS_NONE, 1000, nullptr, &error);
    gboolean present = false;
    if (v) {
      g_variant_get(v, "(b)", &present);
      g_variant_unref(v);
    }
    g_clear_error(&error);
    return present;
  };
  if (ping())
    return;
  int guard = open((runtime_dir() / "host-manager.lock").c_str(),
                   O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
  if (guard < 0 || flock(guard, LOCK_EX))
    throw std::runtime_error("Manager startup lock unavailable");
  if (!ping()) {
    std::string exe = (root / "libexec/saildroid-app").string();
    char *av[] = {exe.data(), (char *)"--session", nullptr};
    if (!g_spawn_async(nullptr, av, nullptr,
                       (GSpawnFlags)(G_SPAWN_STDOUT_TO_DEV_NULL |
                                     G_SPAWN_STDERR_TO_DEV_NULL),
                       [](gpointer) { if (setsid() < 0) _exit(127); },
                       nullptr, nullptr, &e)) {
      close(guard);
      throw std::runtime_error(e ? e->message : "Cannot start manager");
    }
  }
  bool ready = false;
  for (int i = 0; i < 100; i++) {
    if (ping()) {
      try {
        auto v = call(bus, "GetState", g_variant_new("(s)", ""), nullptr, 500);
        g_variant_unref(v);
        ready = true;
        break;
      } catch (...) {
      }
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(30));
  }
  flock(guard, LOCK_UN);
  close(guard);
  if (!ready)
    throw std::runtime_error("Native manager did not become ready");
}
static void print_limits() {
  rlimit l;
  getrlimit(RLIMIT_NICE, &l);
  std::cout << "{\"uid\":" << getuid() << ",\"nice_limit\":" << l.rlim_cur
            << ",\"effective_capabilities\":0,\"no_new_privs\":"
            << prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) << "}\n";
}
int main(int argc, char **argv) {
  try {
    permissions();
    if (argc == 2 && std::string(argv[1]) == "--print-limits") {
      print_limits();
      return 0;
    }
    auto root = own_root();
    std::string package, service, activity, provider, process, action, owner, install, desktop, instrumentation;
    bool manager = false, broker = false, runtime = false, session = false;
    fs::path requested_root;
    for (int i = 1; i < argc; i++) {
      std::string a = argv[i];
      auto value = [&]() {
        if (++i >= argc)
          throw std::runtime_error("Missing argument");
        return std::string(argv[i]);
      };
      if (a == "--package")
        package = value();
      else if (a == "--instrument-request")
        instrumentation = value();
      else if (a == "--manager")
        manager = true;
      else if (a == "--broker")
        broker = true;
      else if (a == "--service")
        service = value();
      else if (a == "--activity-process")
        activity = value();
      else if (a == "--provider-process")
        provider = value();
      else if (a == "--process")
        process = value();
      else if (a == "--owner-launch")
        owner = value();
      else if (a == "--desktop-token")
        desktop = value();
      else if (a == "--component")
        requested_root = value();
      else if (a == "--install")
        install = value();
      else if (a == "--runtime")
        runtime = true;
      else if (a == "--session")
        session = true;
      else if (a == "--status" || a == "--is-running" || a == "--close" ||
               a == "--dump-threads")
        action = a;
      else if (a == "--debug-log")
        env("SAILDROID_ANDROID_LOG_STDERR", "1");
      else if (a.empty() || a[0] != '-') {
        if (!install.empty())
          throw std::runtime_error("Only one APK source is accepted");
        install = a;
      } else
        throw std::runtime_error("Unknown host option: " + a);
    }
    if (session) {
      unsetenv("LD_PRELOAD");
      int fd =
          open((runtime_dir() / "host-manager.log").c_str(),
               O_CREAT | O_APPEND | O_WRONLY | O_CLOEXEC | O_NOFOLLOW, 0600);
      if (fd < 0)
        throw std::runtime_error("Cannot open manager log");
      dup2(fd, 1);
      dup2(fd, 2);
      close(fd);
      return sd_manager_main(root);
    }
    if (requested_root.empty())
      requested_root = root;
    if (fs::canonical(requested_root) != root)
      throw std::runtime_error("Component identity differs");
    if ((!package.empty()) + (int)manager + (int)broker != 1)
      throw std::runtime_error("Select one host role");
    if (manager)
      package = "org.saildroid.manager";
    if (broker)
      package = "org.saildroid.binder";
    if (!instrumentation.empty() && (manager || broker || !service.empty() || !activity.empty() || !provider.empty() || !install.empty()))
      throw std::runtime_error("Instrumentation requires its own application host");
    if (!desktop.empty() && (desktop != package || !service.empty() || !activity.empty() || !provider.empty() || broker))
      throw std::runtime_error("Desktop identity differs");
    if (!install.empty() && !manager)
      throw std::runtime_error("Only installer accepts APKs");
    if (!service.empty() && (!valid_component(service) || process.empty() ||
                             (owner.empty() && action.empty())))
      throw std::runtime_error("Service ownership required");
    if (!activity.empty() && (!valid_component(activity) || !service.empty() || process.empty() ||
                              (owner.empty() && action.empty())))
      throw std::runtime_error("Activity process ownership required");
    if (!install.empty()) {
      std::string source = install;
      if (source.rfind("file:", 0) == 0) {
        GError *error = nullptr;
        gchar *host = nullptr;
        gchar *path = g_filename_from_uri(source.c_str(), &host, &error);
        if (!path || (host && *host && strcmp(host, "localhost"))) {
          g_free(host);
          g_free(path);
          g_clear_error(&error);
          throw std::runtime_error("Select a local APK file");
        }
        source = path;
        g_free(host);
        g_free(path);
      } else if (source.find("://") != source.npos)
        throw std::runtime_error("Select a local APK file");
      fs::path path = fs::canonical(source);
      if (!fs::is_regular_file(path))
        throw std::runtime_error("APK source is not a regular file");
      install = path.string();
      if (install.size() > 16000)
        throw std::runtime_error("APK source is too long");
    }
    if (!provider.empty() && (!valid_component(provider) || !service.empty() || !activity.empty() || process.empty() ||
                              (owner.empty() && action.empty())))
      throw std::runtime_error("Provider process ownership required");
    instance =
        package +
        (process.empty() ? "" : ".service." + sha(process).substr(0, 16));
    if (!runtime && action.empty()) {
      connect_manager(root);
      environment(root);
      std::vector<std::string> args;
      args.emplace_back((root / "libexec/saildroid-host").string());
      for (int i = 1; i < argc; i++)
        args.emplace_back(argv[i]);
      args.emplace_back("--runtime");
      std::vector<char *> raw;
      for (auto &s : args)
        raw.push_back(s.data());
      raw.push_back(nullptr);
      execv(raw[0], raw.data());
      throw std::runtime_error("Host environment exec failed");
    }
    connect_manager(root);
    if (!action.empty()) {
      auto v = call(bus, "GetState", g_variant_new("(s)", instance.c_str()));
      const char *t;
      g_variant_get(v, "(&s)", &t);
      Json r = Json::parse(t);
      g_variant_unref(v);
      bool live = alive(r);
      if (action == "--is-running")
        return live ? 0 : 1;
      if (action == "--status") {
        r["running"] = live;
        std::cout << r.dump() << '\n';
        return 0;
      }
      if (!live)
        return 0;
      if (action == "--dump-threads") {
        std::cout << control(r, "dump") << '\n';
        return 0;
      }
      v = call(bus, "Close",
               g_variant_new("(ss)", instance.c_str(),
                             r.at("launch_id").get<std::string>().c_str()));
      g_variant_unref(v);
      for (int i = 0; i < 160 && alive(r); i++)
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
      if (alive(r)) {
        signal_owned(r, SIGTERM);
        for (int i = 0; i < 60 && alive(r); i++)
          std::this_thread::sleep_for(std::chrono::milliseconds(50));
      }
      if (alive(r))
        throw std::runtime_error("Host did not close");
      return 0;
    }
    Json app =
        (manager || broker)
            ? Json{{"package", package},
                   {"apk", (root / "share/manager.apk").string()},
                   {"native", (root / "empty-libs").string()},
                   {"icon", (root / "share/icons/saildroid.png").string()},
                   {"data", broker ? "/home/art/data/binder"
                                   : "/home/art/data/manager"}}
            : app_record(package);
    std::string id = "org.saildroid.app.p" + sha(package).substr(0, 20),
                launch = nonce(),
                role = broker            ? "broker"
                       : process.empty() ? "activity"
                                         : "service";
    if (setsid() < 0 && getpgrp() != getpid())
      throw std::runtime_error("Cannot establish host process group");
    Json record = {{"package", package},
                   {"role", role},
                   {"service", service},
                   {"activity_component", activity},
                   {"provider_component", provider},
                   {"process_name", process.empty() ? package : process},
                   {"launch_id", launch},
                   {"owner_launch_id", owner},
                   {"component", root.string()},
                   {"app_id", id},
                   {"socket", (runtime_dir() /
                               ("window-" + launch.substr(0, 20) + ".sock"))
                                  .string()}};
    fs::path logdir = "/home/art/data/logs/" + package;
    fs::create_directories(logdir);
    chmod(logdir.c_str(), 0700);
    auto log = logdir / ("native-" + launch + ".log");
    record["log"] = log.string();
    if (app.contains("_record_sha256"))
      record["app_record_sha256"] = app.at("_record_sha256");
    if (broker)
      record["ready_file"] =
          (runtime_dir() / ("registry-ready-" + launch.substr(0, 20))).string();
    auto v =
        call(bus, "RegisterHost",
             g_variant_new("(ss)", instance.c_str(), record.dump().c_str()));
    gboolean accepted;
    const char *text;
    g_variant_get(v, "(b&s)", &accepted, &text);
    Json result = Json::parse(text);
    g_variant_unref(v);
    if (!accepted) {
      if (role == "activity") {
        std::string request = "activate";
        if (!install.empty()) {
          GError *error = nullptr;
          gchar *uri = g_filename_to_uri(install.c_str(), nullptr, &error);
          if (!uri) {
            std::string reason =
                error ? error->message : "Cannot encode local APK URI";
            g_clear_error(&error);
            throw std::runtime_error(reason);
          }
          request = "open " + std::string(uri);
          g_free(uri);
          if (request.size() > 16380)
            throw std::runtime_error("APK request is too long");
        }
        for (int i = 0; i < (install.empty() ? 100 : 800); i++) {
          try {
            if(install.empty()){
              auto activated=call(bus,"ActivateApplication",g_variant_new("(ss)",instance.c_str(),result.at("launch_id").get<std::string>().c_str()));
              g_variant_unref(activated);
              std::cerr << "SDHOST=existing_request|kind=activate-family|pid=" << result.at("pid") << "|same_host=true\n";
              return 0;
            }
            if (control(result, request) == "requested\n") {
              std::cerr << "SDHOST=existing_request|kind="
                        << (install.empty() ? "activate" : "open-apk")
                        << "|pid=" << result.at("pid") << "|same_host=true\n";
              return 0;
            }
          } catch (...) {
          }
          if (!alive(result))
            throw std::runtime_error("Previous host ended");
          std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
        throw std::runtime_error("Previous window not ready");
      }
      return 0;
    }
    registered = true;
    int fd = open(log.c_str(), O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, 0600);
    if (fd < 0)
      throw std::runtime_error("Cannot open host log");
    dup2(fd, STDOUT_FILENO);
    dup2(fd, STDERR_FILENO);
    close(fd);
    std::cerr << "SDHOST=registered|pid=" << getpid()
              << "|start_ticks=" << start_ticks(getpid())
              << "|component=" << root << "|launch=" << launch << '\n';
    if (fs::exists(root / "lib/libsdstrictmath-fdlibm.so")) {
      Dl_info owner{};
      void *entry = dlsym(RTLD_DEFAULT, "ieee_exp");
      if (!entry || !dladdr(entry, &owner) || !owner.dli_fname ||
          fs::canonical(owner.dli_fname) != root / "lib/libsdstrictmath-fdlibm.so")
        throw std::runtime_error("StrictMath native implementation owner differs");
      std::cerr << "SDHOST=native_math|backend=fdlibm|byte_order=little"
                   "|owner=component-private|host_libc_math=unchanged\n";
    }
    if (fs::exists(root / "lib/libsdcharacter-icu63.so")) {
      Dl_info owner{}, icu_owner{};
      void *entry = dlsym(RTLD_DEFAULT, "_Z21Character_getTypeImplP7_JNIEnvP7_jclassi");
      void *version_entry = dlsym(RTLD_DEFAULT, "u_getVersion_63");
      void *unicode_entry = dlsym(RTLD_DEFAULT, "u_getUnicodeVersion_63");
      if (!entry || !dladdr(entry, &owner) || !owner.dli_fname ||
          fs::canonical(owner.dli_fname) != root / "lib/libsdcharacter-icu63.so" ||
          !version_entry || !unicode_entry || !dladdr(version_entry, &icu_owner) ||
          !icu_owner.dli_fname ||
          fs::canonical(icu_owner.dli_fname) != root / "lib/libicuuc.so.63")
        throw std::runtime_error("Character native implementation owner differs");
      unsigned char version[4]{}, unicode[4]{};
      reinterpret_cast<void (*)(unsigned char *)>(version_entry)(version);
      reinterpret_cast<void (*)(unsigned char *)>(unicode_entry)(unicode);
      if (version[0] != 63 || version[1] != 2 || unicode[0] != 11 || unicode[1] != 0)
        throw std::runtime_error("Character native Unicode data version differs");
      std::cerr << "SDHOST=native_character|backend=icu63|owner=component-private"
                << "|unicode=" << unsigned(unicode[0]) << '.' << unsigned(unicode[1])
                << "|jni_registration=original\n";
    }
    fs::path data = app.at("data").get<std::string>();
    fs::create_directories(data);
    chmod(data.c_str(), 0700);
    for (auto child : {"cache", "files", "code_cache", "device-protected"}) {
      fs::create_directories(data / child);
      chmod((data / child).c_str(), 0700);
    }
    env("SAILDROID_PACKAGE", package);
    env("SAILDROID_DATA_DIR", data);
    env("SAILDROID_CONTROL_SOCKET", record.at("socket"));
    env("SAILDROID_APP_LAUNCH_ID", process.empty() ? launch : owner);
    env("SAILDROID_HOST_INSTANCE", instance);
    env("SAILDROID_HOST_LAUNCH_ID", launch);
    if (role == "activity" && instrumentation.empty()) {
      env("SAILDROID_DESKTOP_ID", id);
      if (app.contains("icon"))
        env("SAILDROID_STARTUP_ICON", app.at("icon"));
    } else
      env("SAILDROID_HEADLESS", "1");
    if (broker)
      env("SAILDROID_READY_FILE", record.at("ready_file"));
    Json manifest = read_json(root / "runtime.json");
    std::string boot, locations;
    for (auto &j : manifest.at("boot_jars")) {
      fs::path path = fs::canonical(root / j.get<std::string>());
      auto relative = path.lexically_relative(root);
      if (relative.empty() || *relative.begin() == "..")
        throw std::runtime_error("Boot entry escaped");
      trusted(path);
      if (!boot.empty())
        boot += ':';
      boot += path.string();
      if (!locations.empty())
        locations += ':';
      locations += "/home/art/api29-root/" + j.get<std::string>();
    }
    auto hidden_api = manifest.value("hidden_api", Json::object());
    if (!hidden_api.empty()) {
      if (hidden_api.at("schema") != "saildroid-hiddenapi-v1" ||
          hidden_api.at("policy") != "enabled" ||
          !hidden_api.at("platform_runtime_boot").get<bool>())
        throw std::runtime_error("Unsupported platform hidden API policy");
      auto platform_runtime = fs::canonical(root / "lib/runtime.jar");
      trusted(platform_runtime);
      // The platform host uses framework internals. Give only its fixed,
      // root-owned DEX the boot domain; APK class loaders remain untrusted.
      boot += ':' + platform_runtime.string();
      locations += ":/home/art/api29-root/lib/runtime.jar";
    }
    std::vector<std::string> args = {
        (root / "libexec/saildroid-app").string(),
        "-Xnoimage-dex2oat",
        "-Xbootclasspath:" + boot,
        "-Xbootclasspath-locations:" + locations,
        "-Djava.library.path=" + (root / "lib").string() + ":" +
            (root / "android-libs").string() + ":/home/art/lib",
        "-Dsaidroid.bridge.library=" + (root / "lib/libsdbridge.so").string(),
        "-Dsaidroid.window.library=" + (root / "lib/libsdwindow.so").string(),
        "-Dsaidroid.ime.library=" + (root / "lib/libsdmaliit.so").string(),
        "-Dsaidroid.native.runtime=" + (root / "android-libs").string(),
        "-Dsaidroid.package=" + package,
        "-Dsaidroid.apk=" + app.at("apk").get<std::string>(),
        "-Dsaidroid.native=" + app.at("native").get<std::string>(),
        "-Dsaidroid.data=" + data.string()};
    bool debuggable=app.value("debuggable",false);
    if (manifest.contains("private_art_agent")) {
      auto art_library = fs::canonical(root / "lib/libart.so");
      trusted(art_library);
      args.push_back("-Dsaidroid.art.library=" + art_library.string());
    }
    size_t hidden_api_option=args.size();
    if (!hidden_api.empty())
      args.push_back("-Xhidden-api-policy:enabled");
    args.push_back(std::string("-Dsaidroid.package.debuggable=")+(debuggable?"true":"false"));
    if(debuggable){args.push_back("-Xcompiler-option");args.push_back("--debuggable");}
    if (manifest.value("binder_device", Json()).is_string())
      args.push_back("-Dsaidroid.binder.driver=" +
                     manifest.at("binder_device").get<std::string>());
    if (!service.empty()) {
      args.push_back("-Dsaidroid.service=" + service);
      args.push_back("-Dsaidroid.process=" + process);
    }
    if (!activity.empty()) {
      args.push_back("-Dsaidroid.activity=" + activity);
      args.push_back("-Dsaidroid.process=" + process);
    }
    if (!provider.empty()) {
      args.push_back("-Dsaidroid.provider=" + provider);
      args.push_back("-Dsaidroid.process=" + process);
    }
    if (!install.empty())
      args.push_back("-Dsaidroid.install.source=" + install);
    if (!instrumentation.empty()) {
      auto request=fs::canonical(instrumentation), owner_data=fs::canonical(data);
      auto relative=request.lexically_relative(owner_data);
      if(relative.empty()||*relative.begin()==".."||!fs::is_regular_file(request)||fs::file_size(request)>65536)
        throw std::runtime_error("Instrumentation request escaped private application data");
      auto request_bytes=read_text(request);
      auto configuration=Json::parse(request_bytes);
      if(!instrumentation_hidden_api_checks(configuration,request_bytes,root,package,app.at("apk").get<std::string>())) {
        if(hidden_api.empty())throw std::runtime_error("Component has no explicit hidden API policy");
        args.at(hidden_api_option)="-Xhidden-api-policy:disabled";
      }
      if(configuration.contains("network_proxy")) {
        auto proxy=configuration.at("network_proxy");
        if(proxy.at("type")!="socks5" || !proxy.at("host").is_string() ||
           !proxy.at("port").is_number_integer())
          throw std::runtime_error("Invalid instrumentation network proxy");
        std::string address=proxy.at("host");
        auto parsed=g_inet_address_new_from_string(address.c_str());
        int port=proxy.at("port").get<int>();
        bool valid=parsed&&g_inet_address_get_family(parsed)==G_SOCKET_FAMILY_IPV4&&
          !g_inet_address_get_is_any(parsed)&&!g_inet_address_get_is_multicast(parsed)&&
          port>=1024&&port<=65535;
        if(parsed)g_object_unref(parsed);
        if(!valid)throw std::runtime_error("Invalid instrumentation SOCKS endpoint");
        args.push_back("-DsocksProxyHost="+address);
        args.push_back("-DsocksProxyPort="+std::to_string(port));
        args.push_back("-DsocksProxyVersion=5");
        args.push_back("-Dsaidroid.network.socks.enabled=true");
        std::cerr<<"SDHOST=instrumentation_network_proxy|type=socks5|host="<<address
                 <<"|port="<<port<<"|scope=process-only|tls=unchanged\n";
      }
      args.push_back("-Dsaidroid.instrumentation.request="+request.string());
    }
    args.push_back("-cp");
    args.push_back((root / "lib/runtime.jar").string());
    args.push_back(broker ? "SdBinderRegistry" : "SdRuntime");
    std::vector<char *> raw;
    for (auto &s : args)
      raw.push_back(s.data());
    raw.push_back(nullptr);
    if (!broker && !manager) {
      // Android application processes start at /. In particular, never inherit
      // a trusted launcher's unsearchable working directory (for example /root).
      if (chdir("/") != 0)
        throw std::runtime_error("Cannot establish Android application working directory");
      std::cerr << "SDHOST=app_working_directory|cwd=/|scope=application-process\n";
      if (manifest.contains("private_commands")) {
        auto commands = manifest.at("private_commands");
        if (commands.at("schema") != "saildroid-private-commands-v1")
          throw std::runtime_error("Unsupported private application commands");
        auto executable = fs::canonical(root / "bin/touch");
        if (executable != root / "bin/touch")
          throw std::runtime_error("Private application commands escaped component");
        trusted(executable);
        const char *inherited = getenv("PATH");
        env("PATH", (root / "bin").string() + ":" +
            (inherited ? inherited : "/usr/bin:/bin"));
        std::cerr << "SDHOST=app_commands|backend=android10-toybox|owner=component-private"
                     "|scope=application-process\n";
      }
      if (!sd_install_app_filesystem_policy())
        throw std::runtime_error("Cannot enforce Android app hardlink restriction");
      std::cerr << "SDHOST=app_filesystem_policy|hardlinks=denied|errno=EACCES"
                   "|existing_threads=synchronized|scope=application-process\n";
    }
    int rc = sd_art_main(args.size(), raw.data());
    state("exited");
    return rc;
  } catch (const std::exception &e) {
    std::cerr << "SDHOST=failed|" << e.what() << '\n';
    return 125;
  }
}
