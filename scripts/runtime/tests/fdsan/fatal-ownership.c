#define _GNU_SOURCE
#include <signal.h>
#include <stdint.h>
#include <jni.h>
extern int bionic_android_fdsan_set_error_level(int);
JNIEXPORT void JNICALL Java_FdOwnershipFatalContract_armFatalOwnership(JNIEnv *env, jclass type) {
    (void)env; (void)type;
    bionic_android_fdsan_set_error_level(3);
}

JNIEXPORT jlongArray JNICALL Java_FdOwnershipFatalContract_alternateSignalStack(JNIEnv *env,jclass type){
    (void)type;stack_t stack;if(sigaltstack(NULL,&stack)!=0)return NULL;
    jlong values[3]={(jlong)(intptr_t)stack.ss_sp,(jlong)stack.ss_size,(jlong)(intptr_t)__builtin_frame_address(0)};
    jlongArray result=(*env)->NewLongArray(env,3);if(result)(*env)->SetLongArrayRegion(env,result,0,3,values);return result;
}

#include <stdlib.h>
JNIEXPORT void JNICALL Java_FdOwnershipFatalContract_largeSignalStackDiagnostic(JNIEnv *env,jclass type){
    (void)type;stack_t stack;stack.ss_size=256*1024;stack.ss_sp=malloc(stack.ss_size);stack.ss_flags=0;
    if(!stack.ss_sp||sigaltstack(&stack,NULL)!=0){jclass error=(*env)->FindClass(env,"java/lang/AssertionError");if(error)(*env)->ThrowNew(env,error,"Diagnostic alternate stack allocation failed");}
}
