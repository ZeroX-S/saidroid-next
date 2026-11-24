#define _GNU_SOURCE
#include <errno.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <netinet/in.h>

/* Own negative-test fixture only. Add a per-process kernel denial for ICMP
 * datagram sockets; preserve DNS/UDP/TCP, host sysctls and every other process. */
int main(int argc, char **argv) {
    if (argc < 2 || argv[1][0] != '/' || !getuid() || getuid() != geteuid()) {
        fputs("NETWORK287_DENY_ICMP=refused|ordinary-caller-and-absolute-command-required\n", stderr);
        return 125;
    }
    struct sock_filter code[] = {
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, AUDIT_ARCH_AARCH64, 1, 0),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_KILL),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, __NR_socket, 0, 11),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, AF_INET, 1, 0),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, AF_INET6, 0, 8),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[1])),
        BPF_STMT(BPF_ALU|BPF_AND|BPF_K, 15),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SOCK_DGRAM, 0, 5),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[2])),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, IPPROTO_ICMP, 2, 0),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, IPPROTO_ICMPV6, 1, 0),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|(EACCES&SECCOMP_RET_DATA)),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW)
    };
    struct sock_fprog program = { sizeof(code)/sizeof(code[0]), code };
    if (prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0) || prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&program)) {
        perror("NETWORK287_DENY_ICMP=kernel-filter-failed");return 125;
    }
    fputs("NETWORK287_DENY_ICMP=installed|scope=current-process-descendants|global-network-unchanged=true\n", stderr);
    execv(argv[1],argv+1);perror("NETWORK287_DENY_ICMP=exec-failed");return 125;
}
