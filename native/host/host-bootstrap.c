#define _GNU_SOURCE
#include <limits.h>
#include <linux/capability.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
/* Only this small entry has CAP_DAC_OVERRIDE and CAP_SYS_RESOURCE. It resets
 * its inherited OOM protection and scheduling limit, then execs the unprivileged
 * native host before any window exists, preserving the desktop caller PID.
 * A file-capability executable cannot safely self-exec to enable LD_PRELOAD:
 * glibc's secure-execution mode strips those variables again. */
int main(int argc, char **argv) {
  (void)argc;
  if (!getuid() || geteuid() != getuid()) {
    fputs("Run SailDroid as the phone user\n", stderr);
    return 125;
  }
  /* Some vendor kernels expose this self-only control with mode 0400.
   * Clear the desktop service's protection before spawning any app children. */
  FILE *oom_score = fopen("/proc/self/oom_score_adj", "r");
  if (!oom_score) {
    perror("SailDroid OOM adjustment open");
    return 125;
  }
  int adjustment;
  int read = fscanf(oom_score, "%d", &adjustment);
  int closed = fclose(oom_score);
  if (read != 1 || closed == EOF) {
    fputs("SailDroid OOM adjustment read failed\n", stderr);
    return 125;
  }
  /* Children of the unprivileged host inherit no_new_privs and zero already.
   * Their exec cannot acquire file capabilities, so retain that verified zero. */
  if (adjustment != 0) {
    oom_score = fopen("/proc/self/oom_score_adj", "w");
    if (!oom_score) {
      perror("SailDroid OOM adjustment open");
      return 125;
    }
    int written = fputs("0\n", oom_score);
    closed = fclose(oom_score);
    if (written == EOF || closed == EOF) {
      fputs("SailDroid OOM adjustment write failed\n", stderr);
      return 125;
    }
  }
  struct rlimit current;
  if (getrlimit(RLIMIT_NICE, &current))
    return 125;
  if (current.rlim_cur < 40) {
    struct rlimit limit = {40, 40};
    if (setrlimit(RLIMIT_NICE, &limit)) {
      perror("SailDroid scheduling setup");
      return 125;
    }
  }
  struct __user_cap_header_struct header = {_LINUX_CAPABILITY_VERSION_3, 0};
  struct __user_cap_data_struct caps[2] = {{0}};
  if (syscall(SYS_capset, &header, caps) ||
      prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0))
    return 125;
  fputs("SDHOST=oom_policy|adjustment=0|scope=application-process\n", stderr);
  char path[PATH_MAX];
  ssize_t count = readlink("/proc/self/exe", path, sizeof(path) - 1);
  if (count <= 0 || count >= (ssize_t)sizeof(path) - 1)
    return 125;
  path[count] = 0;
  char *last = strrchr(path, '/');
  if (!last)
    return 125;
  if (sizeof(path) - (size_t)(last + 1 - path) < sizeof("saildroid-host"))
    return 125;
  strcpy(last + 1, "saildroid-host");
  struct stat status;
  if (lstat(path, &status) || !S_ISREG(status.st_mode) || status.st_uid ||
      (status.st_mode & 022)) {
    fputs("Untrusted SailDroid native host\n", stderr);
    return 125;
  }
  argv[0] = path;
  execv(path, argv);
  perror("SailDroid native host exec");
  return 125;
}
