#define _GNU_SOURCE
#include <stdbool.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <unistd.h>
#include <signal.h>
#include <ucontext.h>
#include <sys/syscall.h>
#include <sys/uio.h>
#include <fcntl.h>
#include <dlfcn.h>

/* Opt-in failure evidence only. No allocation, unwinder, or signal suppression:
 * preserve the allocator's first failure even when ART's crash printer cannot
 * allocate. Android ELF mappings are symbolized offline from this same capture. */
static atomic_flag printing=ATOMIC_FLAG_INIT;
static void literal(const char *text){size_t size=0;while(text[size])size++;(void)write(2,text,size);}
static void number(uintptr_t value){
    char hex[19]="0x0000000000000000";
    for(int i=0;i<16;i++)hex[17-i]="0123456789abcdef"[(value>>(i*4))&15];
    (void)write(2,hex,18);
}
static void frames(const char *kind,uintptr_t pc,uintptr_t fp,uintptr_t sp){
    if(atomic_flag_test_and_set(&printing))return;
    literal("\nSDNATIVE_FAILURE=begin|kind=");literal(kind);literal("|tid=");number((uintptr_t)syscall(SYS_gettid));literal("|pc=");number(pc);literal("\n");
    for(unsigned i=0;i<48;i++){
        if((fp&15)||fp<sp||fp-sp>8*1024*1024)break;
        uintptr_t pair[2];struct iovec local={pair,sizeof(pair)},remote={(void*)fp,sizeof(pair)};
        if(syscall(SYS_process_vm_readv,getpid(),&local,1,&remote,1,0)!=(ssize_t)sizeof(pair))break;
        literal("SDNATIVE_FRAME=");number(pair[1]);literal("|fp=");number(fp);literal("\n");
        if(pair[0]<=fp)break;fp=pair[0];
    }
    literal("SDNATIVE_MAPS=begin\n");
    int fd=open("/proc/self/maps",O_RDONLY|O_CLOEXEC);
    if(fd>=0){char buffer[4096];ssize_t length;while((length=read(fd,buffer,sizeof(buffer)))>0)(void)write(2,buffer,(size_t)length);close(fd);}
    literal("SDNATIVE_FAILURE=end\n");atomic_flag_clear(&printing);
}
static bool fatal_signal(int signal,siginfo_t *info,void *context){
    literal("SDNATIVE_FAULT=address|");number((uintptr_t)info->si_addr);literal("|code=");number((uintptr_t)info->si_code);literal("\n");
#if defined(__aarch64__)
    ucontext_t *state=context;frames(signal==SIGABRT?"SIGABRT":signal==SIGTRAP?"SIGTRAP":"SIGSEGV",state->uc_mcontext.pc,state->uc_mcontext.regs[29],state->uc_mcontext.sp);
#else
    (void)context;
#endif
    return false;
}
void sd_failure_diagnostics_install(void){
    static int installed;if(installed)return;
    struct action {bool(*handler)(int,siginfo_t*,void*);sigset_t mask;uint64_t flags;};
    void(*add)(int,struct action*)=dlsym(RTLD_DEFAULT,"AddSpecialSignalHandlerFn");
    if(!add){
        /* JniInvocation deliberately keeps ART and its signal chain local.
         * Resolve that already loaded instance without changing its scope. */
        void *art=dlopen("libart.so",RTLD_NOW|RTLD_NOLOAD);
        if(art)add=dlsym(art,"AddSpecialSignalHandlerFn");
    }
    if(!add){literal("SDNATIVE_DIAGNOSTICS=unavailable\n");return;}
    struct action action={.handler=fatal_signal};sigfillset(&action.mask);add(SIGABRT,&action);
    // ART's existing first special handler gets managed null checks first.
    // Only unhandled native faults reach this later diagnostic handler.
    add(SIGSEGV,&action);add(SIGTRAP,&action);installed=1;
    literal("SDNATIVE_DIAGNOSTICS=installed|signal=SIGABRT,SIGSEGV,SIGTRAP|policy=continue-existing-chain\n");
}
static void termination(int signal){
    const char *enabled=getenv("SAILDROID_ANDROID_LOG_STDERR");if(!enabled||*enabled!='1'||(signal!=SIGKILL&&signal!=SIGABRT&&signal!=SIGTERM))return;
    uintptr_t fp=(uintptr_t)__builtin_frame_address(0);
    literal("SDNATIVE_TERMINATION=signal|");number((uintptr_t)signal);literal("\n");
    frames("termination-call",(uintptr_t)__builtin_return_address(0),fp,fp);
}
int bionic_kill(pid_t pid,int signal){termination(signal);return (int)syscall(SYS_kill,pid,signal);}
int bionic_tgkill(pid_t pid,pid_t tid,int signal){termination(signal);return (int)syscall(SYS_tgkill,pid,tid,signal);}
