#pragma once
#include "third_party/json.hpp"
#include <chrono>
#include <fcntl.h>
#include <filesystem>
#include <fstream>
#include <gio/gio.h>
#include <iostream>
#include <regex>
#include <signal.h>
#include <sstream>
#include <stdexcept>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <thread>
#include <unistd.h>
using Json = nlohmann::json;
namespace fs = std::filesystem;
static inline bool valid_component(const std::string &name) {
  return std::regex_match(
      name, std::regex("[A-Za-z_$][A-Za-z0-9_$]*(\\.[A-Za-z_$][A-Za-z0-9_$]*)+"));
}
static const char *BUS = "org.saildroid.HostManager",
                  *OBJECT = "/org/saildroid/HostManager",
                  *IFACE = "org.saildroid.HostManager1";
inline std::string read_text(const fs::path &p) {
  std::ifstream f(p);
  if (!f)
    throw std::runtime_error("Cannot read " + p.string());
  return std::string(std::istreambuf_iterator<char>(f), {});
}
inline Json read_json(const fs::path &p) { return Json::parse(read_text(p)); }
inline std::string boot_id() {
  auto s = read_text("/proc/sys/kernel/random/boot_id");
  if (!s.empty() && s.back() == '\n')
    s.pop_back();
  return s;
}
inline uint64_t start_ticks(pid_t pid) {
  std::string s = read_text("/proc/" + std::to_string(pid) + "/stat");
  std::istringstream in(s.substr(s.rfind(") ") + 2));
  std::string word;
  for (int i = 0; i < 20; i++)
    in >> word;
  return std::stoull(word);
}
inline bool alive(const Json &r) {
  try {
    pid_t pid = r.at("pid");
    if (pid <= 1 || r.at("boot") != boot_id() ||
        r.at("start_ticks").get<uint64_t>() != start_ticks(pid))
      return false;
    std::string s = read_text("/proc/" + std::to_string(pid) + "/status");
    std::istringstream in(s.substr(s.find("Uid:") + 4));
    unsigned uid;
    in >> uid;
    if (uid != getuid())
      return false;
    if (r.contains("component")) {
      fs::path expected = fs::path(r.at("component").get<std::string>()) /
                          "libexec/saildroid-host";
      if (fs::canonical("/proc/" + std::to_string(pid) + "/exe") != expected)
        return false;
    }
    auto at = s.find("State:");
    return at != s.npos && s.substr(at, 24).find('Z') == std::string::npos &&
           s.substr(at, 24).find('X') == std::string::npos;
  } catch (...) {
    return false;
  }
}
inline void save_json(const fs::path &p, const Json &v) {
  std::string temp = p.string() + ".tmp-" + std::to_string(getpid());
  int fd = open(temp.c_str(),
                O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC | O_NOFOLLOW, 0600);
  if (fd < 0)
    throw std::runtime_error("Cannot create state");
  std::string s = v.dump(2) + "\n";
  size_t n = 0;
  while (n < s.size()) {
    ssize_t k = write(fd, s.data() + n, s.size() - n);
    if (k <= 0) {
      close(fd);
      unlink(temp.c_str());
      throw std::runtime_error("State write failed");
    }
    n += k;
  }
  fsync(fd);
  close(fd);
  if (rename(temp.c_str(), p.c_str())) {
    unlink(temp.c_str());
    throw std::runtime_error("State commit failed");
  }
}
inline fs::path runtime_dir() {
  fs::path p = "/run/user/" + std::to_string(getuid()) + "/saildroid";
  struct stat st;
  if (lstat(p.c_str(), &st)) {
    if (errno != ENOENT || mkdir(p.c_str(), 0700))
      throw std::runtime_error("Cannot create runtime directory");
    if (lstat(p.c_str(), &st))
      throw std::runtime_error("Cannot inspect runtime directory");
  }
  if (!S_ISDIR(st.st_mode) || st.st_uid != getuid() || (st.st_mode & 077))
    throw std::runtime_error("Unsafe runtime directory");
  return p;
}
inline std::string sha(const std::string &s) {
  char *v =
      g_compute_checksum_for_string(G_CHECKSUM_SHA256, s.c_str(), s.size());
  std::string result(v);
  g_free(v);
  return result;
}
inline std::string nonce() {
  char *v = g_uuid_string_random();
  std::string s(v);
  g_free(v);
  s.erase(std::remove(s.begin(), s.end(), '-'), s.end());
  return s;
}
inline std::string control(const Json &r, const std::string &verb) {
  if (!alive(r))
    throw std::runtime_error("Host identity ended");
  std::string p = r.at("socket");
  if (p.size() >= sizeof(sockaddr_un::sun_path))
    throw std::runtime_error("Socket path too long");
  int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
  if (fd < 0)
    throw std::runtime_error("Socket failed");
  timeval timeout{2, 0};
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
  setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
  sockaddr_un address{};
  address.sun_family = AF_UNIX;
  strcpy(address.sun_path, p.c_str());
  if (connect(fd, (sockaddr *)&address, sizeof(address))) {
    close(fd);
    throw std::runtime_error("Host endpoint unavailable");
  }
  ucred peer{};
  socklen_t len = sizeof(peer);
  if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &len) ||
      peer.pid != r.at("pid").get<int>() || peer.uid != getuid() || !alive(r)) {
    close(fd);
    throw std::runtime_error("Host endpoint identity differs");
  }
  std::string command = verb + "\n";
  ssize_t sent = send(fd, command.data(), command.size(), MSG_NOSIGNAL);
  char result[64];
  ssize_t count =
      sent == (ssize_t)command.size() ? read(fd, result, sizeof(result)) : -1;
  close(fd);
  if (count <= 0)
    throw std::runtime_error("Host request failed");
  return std::string(result, count);
}
inline GVariant *call(GDBusConnection *c, const char *method, GVariant *args,
                      const GVariantType *type = nullptr, int timeout = 5000) {
  GError *e = nullptr;
  auto r =
      g_dbus_connection_call_sync(c, BUS, OBJECT, IFACE, method, args, type,
                                  G_DBUS_CALL_FLAGS_NONE, timeout, nullptr, &e);
  if (!r) {
    std::string s = e ? e->message : "D-Bus call failed";
    g_clear_error(&e);
    throw std::runtime_error(s);
  }
  return r;
}
inline void signal_owned(const Json &r, int sig) {
  if (alive(r)) {
    pid_t pid = r.at("pid");
    if (getpgid(pid) == pid)
      kill(-pid, sig);
    else
      kill(pid, sig);
  }
}
