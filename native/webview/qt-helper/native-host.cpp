/* Native replacement for SailDroid's shell environment wrapper.
 * The verified external WPE defaults are a component-owned data snapshot. */
#include "../../host/third_party/json.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <signal.h>
#include <string>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>
using Json = nlohmann::json;
namespace fs = std::filesystem;
static void replace(std::string &value, const std::string &from,
                    const std::string &to) {
  size_t at = 0;
  while ((at = value.find(from, at)) != value.npos) {
    value.replace(at, from.size(), to);
    at += to.size();
  }
}
static void trusted(const fs::path &p) {
  struct stat s;
  if (lstat(p.c_str(), &s) || !S_ISREG(s.st_mode) || s.st_uid != 0 ||
      (s.st_mode & 022))
    throw std::runtime_error("Untrusted WebView component input");
}
int main(int argc, char **argv) {
  try {
    if (!getuid() || geteuid() != getuid())
      throw std::runtime_error("Run WebView as the application user");
    const char *profile = getenv("HOME");
    if (!profile || *profile != '/')
      throw std::runtime_error("Private WebView profile missing");
    std::string home = profile;
    fs::path here = fs::canonical("/proc/self/exe").parent_path(),
             config = here / "webview-host-env.json",
             binary = here / "sdwebviewd", qml = here / "webview-engine.qml";
    trusted(config);
    trusted(binary);
    trusted(qml);
    std::ifstream file(config);
    Json input;
    file >> input;
    if (input.at("schema") != 1)
      throw std::runtime_error("Unsupported WebView environment schema");
    unsetenv("LD_PRELOAD");
    unsetenv("LD_LIBRARY_PATH");
    for (auto it = input.at("values").begin(); it != input.at("values").end();
         ++it) {
      std::string value = it.value();
      replace(value, "${SD_PROFILE}", home);
      replace(value, "${SD_COMPONENT}", here.parent_path().string());
      replace(value, "/run/user/100000",
              "/run/user/" + std::to_string(getuid()));
      if (setenv(it.key().c_str(), value.c_str(), 1))
        throw std::runtime_error("Cannot configure WebView environment");
    }
    // The owning ART host's private data paths come from ProcessBuilder, never
    // from the external browser's user profile or its environment script.
    setenv("HOME", home.c_str(), 1);
    pid_t parent = getppid();
    if (prctl(PR_SET_PDEATHSIG, SIGTERM) || getppid() != parent)
      return 69;
    std::cerr << "SDWEBHOST=runtime_env|native=true|source_sha256="
              << input.at("source_sha256").get<std::string>() << '\n';
    std::string target = binary.string(), document = qml.string();
    std::vector<char *> args{target.data(), document.data()};
    for (int i = 1; i < argc; i++)
      args.push_back(argv[i]);
    args.push_back(nullptr);
    execv(target.c_str(), args.data());
    throw std::runtime_error("Cannot exec native WebView helper");
  } catch (const std::exception &e) {
    std::cerr << "SDWEBHOST=failed|" << e.what() << '\n';
    return 69;
  }
}
