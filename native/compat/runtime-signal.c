#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdatomic.h>
#include <string.h>

/* Android ARM64 has an eight-byte sigset_t and a different sigaction layout.
 * Never pass those buffers to a glibc API, whose sigset_t is 128 bytes.
 * The standalone ART fork exposes its signal interception under explicit
 * sigchain_* names, so Android callers must enter that chain as well. */
struct sd_bionic_sigaction {
    int flags;
    union { void (*handler)(int); void (*action)(int, siginfo_t *, void *); } callback;
    uint64_t mask;
    void (*restorer)(void);
};
_Static_assert(offsetof(struct sd_bionic_sigaction, callback)==8,"ARM64 signal ABI");
_Static_assert(sizeof(struct sd_bionic_sigaction)==32,"ARM64 signal ABI");

typedef int(*action_function)(int,const struct sigaction *,struct sigaction *);
typedef int(*mask_function)(int,const sigset_t *,sigset_t *);
static pthread_mutex_t signal_lock=PTHREAD_MUTEX_INITIALIZER;
static _Atomic(action_function) chain_action;
static _Atomic(mask_function) chain_mask;
static void resolve_signal_chain(void) {
    if(atomic_load(&chain_action))return;
    pthread_mutex_lock(&signal_lock);
    // The executable may export its own signal-chain table. Match ART's ELF
    // symbol resolution first; a direct library lookup can select a second,
    // unclaimed table and silently replace the VM's kernel handler.
    action_function action=dlsym(RTLD_DEFAULT,"sigchain_sigaction");
    mask_function mask=dlsym(RTLD_DEFAULT,"sigchain_sigprocmask");
    if(!action||!mask){
        void *handle=dlopen("libsigchain.so",RTLD_NOW|RTLD_NOLOAD);
        if(handle){action=dlsym(handle,"sigchain_sigaction");mask=dlsym(handle,"sigchain_sigprocmask");}
    }
    // Calls can precede VM initialization. Do not permanently cache a libc
    // fallback before ART's signal chain has been loaded into this process.
    if(action&&mask){atomic_store(&chain_mask,mask);atomic_store(&chain_action,action);}
    pthread_mutex_unlock(&signal_lock);
}
static int host_signal(int number) {
    /* Keep the translator's existing libbacktrace signal mapping. */
    return number==33?SIGRTMIN:number;
}
static void to_host_mask(uint64_t input,sigset_t *output) {
    sigemptyset(output);
    for(int number=1;number<=64;number++)
        if(input&(UINT64_C(1)<<(number-1)))sigaddset(output,host_signal(number));
}
static uint64_t from_host_mask(const sigset_t *input) {
    uint64_t output=0;
    for(int number=1;number<=64;number++)
        if(sigismember(input,host_signal(number))==1)output|=UINT64_C(1)<<(number-1);
    return output;
}
int bionic_sigaction(int number,const struct sd_bionic_sigaction *input,
        struct sd_bionic_sigaction *output) {
    resolve_signal_chain();
    struct sigaction action={0},previous={0};
    if(input) {
        action.sa_sigaction=input->callback.action;
        action.sa_flags=input->flags;
        action.sa_restorer=input->restorer;
        to_host_mask(input->mask,&action.sa_mask);
    }
    action_function call=atomic_load(&chain_action);if(!call)call=sigaction;
    int result=call(host_signal(number),input?&action:NULL,output?&previous:NULL);
    if(result==0&&output) {
        memset(output,0,sizeof(*output));
        output->flags=previous.sa_flags;
        output->callback.action=previous.sa_sigaction;
        output->mask=from_host_mask(&previous.sa_mask);
        output->restorer=previous.sa_restorer;
    }
    return result;
}
int bionic_sigaction64(int number,const struct sd_bionic_sigaction *input,
        struct sd_bionic_sigaction *output) {return bionic_sigaction(number,input,output);}
void (*bionic_signal(int number,void (*handler)(int)))(int) {
    struct sd_bionic_sigaction action={.flags=SA_RESTART},previous;
    action.callback.handler=handler;
    return bionic_sigaction(number,&action,&previous)==0?previous.callback.handler:SIG_ERR;
}
int bionic_sigprocmask(int how,const uint64_t *input,uint64_t *output) {
    resolve_signal_chain();
    sigset_t mask,previous;
    if(input)to_host_mask(*input,&mask);
    mask_function call=atomic_load(&chain_mask);if(!call)call=sigprocmask;
    int result=call(how,input?&mask:NULL,output?&previous:NULL);
    if(result==0&&output)*output=from_host_mask(&previous);
    return result;
}
int bionic_pthread_sigmask(int how,const uint64_t *input,uint64_t *output) {
    int saved=errno;
    int result=bionic_sigprocmask(how,input,output);
    int error=result==0?0:errno;
    errno=saved;
    return error;
}
int bionic_sigemptyset(uint64_t *set) {if(!set){errno=EINVAL;return -1;}*set=0;return 0;}
int bionic_sigfillset(uint64_t *set) {if(!set){errno=EINVAL;return -1;}*set=UINT64_MAX;return 0;}
static int valid_signal(const uint64_t *set,int number) {if(!set||number<1||number>64){errno=EINVAL;return 0;}return 1;}
int bionic_sigaddset(uint64_t *set,int number) {if(!valid_signal(set,number))return -1;*set|=UINT64_C(1)<<(number-1);return 0;}
int bionic_sigdelset(uint64_t *set,int number) {if(!valid_signal(set,number))return -1;*set&=~(UINT64_C(1)<<(number-1));return 0;}
int bionic_sigismember(const uint64_t *set,int number) {return valid_signal(set,number)?!!(*set&(UINT64_C(1)<<(number-1))):-1;}
