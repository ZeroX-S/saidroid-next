#define _GNU_SOURCE
#include <jni.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

/* Actual app-owned diagnostic records, not the host Android logd. Matching
 * Android liblog performs the binary value encoding and size elision. The
 * bounded private file shares records with this application's other processes.
 * It does not expose system/other-app logs or implement logd wrap waiting. */
#define CAPACITY (1024U*1024U)
#define PAYLOAD_MAX 4068U
#define HEADER_SIZE 28U
static void *(*new_logger)(uint32_t);
static int (*put_int)(void*,int32_t),(*put_long)(void*,int64_t),(*put_float)(void*,float);
static int (*put_string)(void*,const char*),(*get_buffer)(void*,const char**),(*destroy_logger)(void**);
static jclass event_class,string_class,integer_class,long_class,float_class;
static jmethodID event_constructor,collection_add;
static jfieldID integer_value,long_value,float_value;
static void fail(JNIEnv *env,const char *type,const char *message){jclass c=(*env)->FindClass(env,type);if(c)(*env)->ThrowNew(env,c,message);}
static void io_fail(JNIEnv *env,int error){char message[128];snprintf(message,sizeof(message),"Private EventLog: %s",strerror(error));fail(env,"java/io/IOException",message);}
static uint16_t get16(const unsigned char *p){return p[0]|((uint16_t)p[1]<<8);}
static uint32_t get32(const unsigned char *p){return p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static void put16(unsigned char *p,uint16_t v){p[0]=v;p[1]=v>>8;}
static void put32(unsigned char *p,uint32_t v){for(int i=0;i<4;i++)p[i]=(unsigned char)(v>>(i*8));}
static int open_log(void){
 const char *data=getenv("SAILDROID_DATA_DIR");char *canonical=data?realpath(data,NULL):NULL;
 if(!canonical){errno=ENODEV;return -1;}
 if(strcmp(canonical,data)){free(canonical);errno=EACCES;return -1;}free(canonical);
 int directory=open(data,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(directory<0)return -1;
 struct stat info;
 if(fstat(directory,&info)||info.st_uid!=geteuid()||(info.st_mode&0022)){close(directory);errno=EACCES;return -1;}
 int fd=openat(directory,".saildroid-eventlog",O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC,0600);int saved=errno;close(directory);errno=saved;
 if(fd<0)return -1;
 if(fstat(fd,&info)||!S_ISREG(info.st_mode)||info.st_uid!=geteuid()||info.st_nlink!=1||(info.st_mode&0077)){close(fd);errno=EACCES;return -1;}
 return fd;
}
/* The only discard permitted here is an incomplete final write. A malformed
 * complete header fails rather than turning arbitrary bytes into an event. */
static int valid_bytes(const unsigned char *data,size_t size,size_t *valid){
 size_t at=0;
 while(size-at>=HEADER_SIZE){
  size_t payload=get16(data+at),header=get16(data+at+2);
  if(header!=HEADER_SIZE||payload<4||payload>PAYLOAD_MAX||get32(data+at+20)!=2)return EILSEQ;
  if(size-at<header+payload)break;
  at+=header+payload;
 }
 *valid=at;return 0;
}
static int snapshot(int fd,unsigned char **out,size_t *size){
 struct stat info;if(fstat(fd,&info))return errno;if(info.st_size<0||info.st_size>CAPACITY)return EFBIG;
 size_t length=(size_t)info.st_size;unsigned char *data=malloc(length?length:1);if(!data)return ENOMEM;
 size_t at=0;
 while(at<length){ssize_t n=pread(fd,data+at,length-at,(off_t)at);if(n<0&&errno==EINTR)continue;if(n<=0){int e=n<0?errno:EIO;free(data);return e;}at+=(size_t)n;}
 int e=valid_bytes(data,length,size);if(e){free(data);return e;}*out=data;return 0;
}
static int write_all(int fd,const unsigned char *data,size_t size,off_t offset){
 while(size){ssize_t n=pwrite(fd,data,size,offset);if(n<0&&errno==EINTR)continue;if(n<=0)return n<0?errno:EIO;data+=n;size-=(size_t)n;offset+=n;}return 0;
}
static int append_event(jint tag,const char *payload,size_t size){
 if(size>PAYLOAD_MAX-4)return -EOVERFLOW;
 unsigned char entry[HEADER_SIZE+PAYLOAD_MAX];struct timespec now;
 if(clock_gettime(CLOCK_REALTIME,&now))return -errno;
 put16(entry,(uint16_t)(size+4));put16(entry+2,HEADER_SIZE);put32(entry+4,(uint32_t)getpid());put32(entry+8,(uint32_t)syscall(SYS_gettid));put32(entry+12,(uint32_t)now.tv_sec);put32(entry+16,(uint32_t)now.tv_nsec);put32(entry+20,2);put32(entry+24,(uint32_t)getuid());put32(entry+HEADER_SIZE,(uint32_t)tag);memcpy(entry+HEADER_SIZE+4,payload,size);
 int fd=open_log();if(fd<0)return -errno;
 if(flock(fd,LOCK_EX)){int e=errno;close(fd);return -e;}
 unsigned char *old=NULL;size_t old_size=0;int error=snapshot(fd,&old,&old_size);size_t skip=0,length=HEADER_SIZE+4+size;
 if(!error){
  while(old_size-skip+length>CAPACITY)skip+=HEADER_SIZE+get16(old+skip);
  if(skip)error=write_all(fd,old+skip,old_size-skip,0);
  if(!error)error=write_all(fd,entry,length,(off_t)(old_size-skip));
  if(!error&&ftruncate(fd,(off_t)(old_size-skip+length)))error=errno;
 }
 free(old);flock(fd,LOCK_UN);close(fd);return error?-error:(int)(size+4);
}
static jint finish(void *context,jint tag){
 const char *payload=NULL;int count=get_buffer(context,&payload);
 /* liblog's string encoder can report its pre-elision cursor. Android's
  * writer caps the complete tag+payload at LOGGER_ENTRY_MAX_PAYLOAD; apply
  * that same transport limit before reading the encoder's bounded storage. */
 if(count>(int)(PAYLOAD_MAX-4))count=(int)(PAYLOAD_MAX-4);
 int result=count<0?count:append_event(tag,payload,(size_t)count);destroy_logger(&context);return result;
}
static jint write_int(JNIEnv *e,jclass c,jint tag,jint value){(void)e;(void)c;void *ctx=new_logger((uint32_t)tag);if(!ctx)return -ENOMEM;put_int(ctx,value);return finish(ctx,tag);}
static jint write_long(JNIEnv *e,jclass c,jint tag,jlong value){(void)e;(void)c;void *ctx=new_logger((uint32_t)tag);if(!ctx)return -ENOMEM;put_long(ctx,value);return finish(ctx,tag);}
static jint write_float(JNIEnv *e,jclass c,jint tag,jfloat value){(void)e;(void)c;void *ctx=new_logger((uint32_t)tag);if(!ctx)return -ENOMEM;put_float(ctx,value);return finish(ctx,tag);}
static int add_string(JNIEnv *e,void *ctx,jstring value,const char *null_value){
 const char *text=value?(*e)->GetStringUTFChars(e,value,NULL):null_value;if(!text)return -1;
 int result=put_string(ctx,text);if(value)(*e)->ReleaseStringUTFChars(e,value,text);return result;
}
static jint write_string(JNIEnv *e,jclass c,jint tag,jstring value){(void)c;void *ctx=new_logger((uint32_t)tag);if(!ctx)return -ENOMEM;add_string(e,ctx,value,"NULL");if((*e)->ExceptionCheck(e)){destroy_logger(&ctx);return -1;}return finish(ctx,tag);}
static jint write_array(JNIEnv *e,jclass c,jint tag,jobjectArray values){
 (void)c;void *ctx=new_logger((uint32_t)tag);if(!ctx)return -ENOMEM;int result=0;
 if(!values)result=put_string(ctx,"[NULL]");
 else for(jsize i=0,length=(*e)->GetArrayLength(e,values);i<length&&i<255&&result>=0;i++){
  jobject item=(*e)->GetObjectArrayElement(e,values,i);
  if(!item)result=put_string(ctx,"NULL");
  else if((*e)->IsInstanceOf(e,item,string_class))result=add_string(e,ctx,(jstring)item,"NULL");
  else if((*e)->IsInstanceOf(e,item,integer_class))result=put_int(ctx,(*e)->GetIntField(e,item,integer_value));
  else if((*e)->IsInstanceOf(e,item,long_class))result=put_long(ctx,(*e)->GetLongField(e,item,long_value));
  else if((*e)->IsInstanceOf(e,item,float_class))result=put_float(ctx,(*e)->GetFloatField(e,item,float_value));
  else fail(e,"java/lang/IllegalArgumentException","Invalid payload item type");
  if(item)(*e)->DeleteLocalRef(e,item);
  if((*e)->ExceptionCheck(e)){destroy_logger(&ctx);return -1;}
 }
 return finish(ctx,tag);
}
static void read_events(JNIEnv *e,jclass c,jintArray tags,jobject output){
 (void)c;if(!tags||!output){fail(e,"java/lang/NullPointerException","tags and output required");return;}
 int fd=open_log();if(fd<0){io_fail(e,errno);return;}if(flock(fd,LOCK_SH)){int error=errno;close(fd);io_fail(e,error);return;}
 unsigned char *data=NULL;size_t size=0;int error=snapshot(fd,&data,&size);flock(fd,LOCK_UN);close(fd);if(error){io_fail(e,error);return;}
 jsize count=(*e)->GetArrayLength(e,tags);jint *wanted=(*e)->GetIntArrayElements(e,tags,NULL);if(!wanted){free(data);return;}
 for(size_t at=0;at<size;){
  size_t length=HEADER_SIZE+get16(data+at);int32_t tag=(int32_t)get32(data+at+HEADER_SIZE);int match=0;
  for(jsize i=0;i<count;i++)if(tag==wanted[i]){match=1;break;}
  if(match){
   jbyteArray bytes=(*e)->NewByteArray(e,(jsize)length);if(!bytes)break;
   (*e)->SetByteArrayRegion(e,bytes,0,(jsize)length,(const jbyte*)data+at);
   jobject event=(*e)->ExceptionCheck(e)?NULL:(*e)->NewObject(e,event_class,event_constructor,bytes);(*e)->DeleteLocalRef(e,bytes);
   if(event){(*e)->CallBooleanMethod(e,output,collection_add,event);(*e)->DeleteLocalRef(e,event);}
   if((*e)->ExceptionCheck(e))break;
  }
  at+=length;
 }
 (*e)->ReleaseIntArrayElements(e,tags,wanted,JNI_ABORT);free(data);
}
static void read_wrap(JNIEnv *e,jclass c,jintArray tags,jlong time,jobject output){(void)c;(void)tags;(void)time;(void)output;fail(e,"java/lang/UnsupportedOperationException","System logd wrap waiting is unavailable for app-private EventLog");}
int sd_event_log_install(JNIEnv *e,void *(*lookup)(const char*)){
#define LOAD(target,name) do{*(void **)(&target)=lookup(name);if(!target)return -1;}while(0)
 LOAD(new_logger,"create_android_logger");LOAD(put_int,"android_log_write_int32");LOAD(put_long,"android_log_write_int64");LOAD(put_float,"android_log_write_float32");LOAD(put_string,"android_log_write_string8");LOAD(get_buffer,"android_log_write_list_buffer");LOAD(destroy_logger,"android_log_destroy");
#undef LOAD
#define CLASS(target,name) do{jclass local=(*e)->FindClass(e,name);if(!local)return -1;target=(*e)->NewGlobalRef(e,local);(*e)->DeleteLocalRef(e,local);if(!target)return -1;}while(0)
 CLASS(event_class,"android/util/EventLog$Event");CLASS(string_class,"java/lang/String");CLASS(integer_class,"java/lang/Integer");CLASS(long_class,"java/lang/Long");CLASS(float_class,"java/lang/Float");
#undef CLASS
 event_constructor=(*e)->GetMethodID(e,event_class,"<init>","([B)V");jclass collection=(*e)->FindClass(e,"java/util/Collection");if(!collection)return -1;collection_add=(*e)->GetMethodID(e,collection,"add","(Ljava/lang/Object;)Z");(*e)->DeleteLocalRef(e,collection);
 integer_value=(*e)->GetFieldID(e,integer_class,"value","I");long_value=(*e)->GetFieldID(e,long_class,"value","J");float_value=(*e)->GetFieldID(e,float_class,"value","F");
 if((*e)->ExceptionCheck(e)||!event_constructor||!collection_add||!integer_value||!long_value||!float_value)return -1;
 JNINativeMethod methods[]={{"writeEvent","(II)I",write_int},{"writeEvent","(IJ)I",write_long},{"writeEvent","(IF)I",write_float},{"writeEvent","(ILjava/lang/String;)I",write_string},{"writeEvent","(I[Ljava/lang/Object;)I",write_array},{"readEvents","([ILjava/util/Collection;)V",read_events},{"readEventsOnWrapping","([IJLjava/util/Collection;)V",read_wrap}};
 jclass type=(*e)->FindClass(e,"android/util/EventLog");if(!type)return -1;int result=(*e)->RegisterNatives(e,type,methods,sizeof(methods)/sizeof(methods[0]));(*e)->DeleteLocalRef(e,type);return result;
}
