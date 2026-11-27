#define _GNU_SOURCE
#include <regex.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <limits.h>

/* AOSP android-10.0.0_r1 bionic/libc/include/regex.h uses the BSD ABI:
 * regex_t is32 bytes on ARM64, and regoff_t is ssize_t. glibc's regex_t
 * is64 bytes and regoff_t is int. Neither object may cross this boundary. */
struct sd_regex {int magic;size_t nsub;const char *end;void *guts;};
struct sd_match {ssize_t start,end;};
struct host_regex {regex_t value;int nosub;};
_Static_assert(sizeof(struct sd_regex)==32,"Android ARM64 regex_t ABI");
_Static_assert(sizeof(struct sd_match)==16,"Android ARM64 regmatch_t ABI");
#define MAGIC 0x53445258
static int android_error(int code){
    if(code<=REG_BADRPT)return code;
    if(code==REG_ESIZE)return 12;
    if(code==REG_ERPAREN)return 8;
    return 2;
}
int bionic_regcomp(struct sd_regex *out,const char *pattern,int flags){
    if(!out||!pattern)return 16;
    const char *end=(flags&32)?out->end:NULL;
    out->magic=0;out->nsub=0;out->guts=NULL;
    if((flags&~(1|2|4|8|16|32|128))||((flags&16)&&(flags&1)))return 16;
    size_t length;
    if(flags&32){
        if((uintptr_t)end<(uintptr_t)pattern)return 16;
        length=(uintptr_t)end-(uintptr_t)pattern;
        // glibc regcomp takes a C string; embedded-NUL patterns are unsupported.
        if(memchr(pattern,0,length))return 16;
    }else length=strlen(pattern);
    if(length>(SIZE_MAX-1)/2)return 12;
    char *copy=NULL;
    if(flags&(16|32)){
        copy=malloc(length*2+1);if(!copy)return 12;
        size_t used=0;
        for(size_t i=0;i<length;i++){
            if((flags&16)&&strchr(".\\[*^$",pattern[i]))copy[used++]='\\';
            copy[used++]=pattern[i];
        }
        copy[used]=0;pattern=copy;
    }
    int mode=((flags&1)?REG_EXTENDED:0)|((flags&2)?REG_ICASE:0)|((flags&4)?REG_NOSUB:0)|((flags&8)?REG_NEWLINE:0);
    struct host_regex *host=calloc(1,sizeof(*host));if(!host){free(copy);return 12;}
    int result=regcomp(&host->value,pattern,mode);free(copy);
    if(result){free(host);return android_error(result);}
    host->nosub=(flags&4)!=0;out->nsub=host->value.re_nsub;out->guts=host;out->magic=MAGIC;return 0;
}
int bionic_regexec(const struct sd_regex *compiled,const char *text,size_t count,struct sd_match *matches,int flags){
    if(!compiled||compiled->magic!=MAGIC||!text||(count&&!matches)||(flags&~(1|2|4|256|512|1024)))return 16;
    struct host_regex *host=compiled->guts;
    size_t slots=host->nosub?0:count;if((flags&4)&&!slots)slots=1;
    if(slots>SIZE_MAX/sizeof(regmatch_t))return 12;
    regmatch_t *temporary=slots?calloc(slots,sizeof(*temporary)):NULL;if(slots&&!temporary)return 12;
    if(flags&4){
        if(!matches||matches[0].start<0||matches[0].end<matches[0].start||matches[0].end>INT_MAX){free(temporary);return 16;}
        temporary[0].rm_so=(regoff_t)matches[0].start;temporary[0].rm_eo=(regoff_t)matches[0].end;
    }
    int mode=((flags&1)?REG_NOTBOL:0)|((flags&2)?REG_NOTEOL:0)|((flags&4)?REG_STARTEND:0);
    int result=regexec(&host->value,text,slots,temporary,mode);
    if(!result&&!host->nosub)for(size_t i=0;i<count;i++){matches[i].start=temporary[i].rm_so;matches[i].end=temporary[i].rm_eo;}
    free(temporary);return android_error(result);
}
void bionic_regfree(struct sd_regex *compiled){
    if(!compiled||compiled->magic!=MAGIC)return;
    struct host_regex *host=compiled->guts;regfree(&host->value);free(host);
    compiled->magic=0;compiled->guts=NULL;compiled->nsub=0;
}
size_t bionic_regerror(int code,const struct sd_regex *compiled,char *buffer,size_t size){
    static const char *names[]={"REG_OK","REG_NOMATCH","REG_BADPAT","REG_ECOLLATE","REG_ECTYPE","REG_EESCAPE","REG_ESUBREG","REG_EBRACK","REG_EPAREN","REG_EBRACE","REG_BADBR","REG_ERANGE","REG_ESPACE","REG_BADRPT","REG_EMPTY","REG_ASSERT","REG_INVARG"};
    static const char *messages[]={"no error","regexec() failed to match","invalid regular expression","invalid collating element","invalid character class","trailing backslash","invalid backreference","unmatched bracket","unmatched parenthesis","unmatched brace","invalid repetition count","invalid character range","out of memory","invalid repetition operator","empty expression","internal regex error","invalid regex argument"};
    const char *message;char temporary[40];
    if(code==255){
        int found=0;if(compiled&&compiled->end)for(int i=1;i<=16;i++)if(!strcmp(compiled->end,names[i])){found=i;break;}
        snprintf(temporary,sizeof(temporary),"%d",found);message=temporary;
    }else if(code&256){int number=code&~256;if(number>=0&&number<=16)message=names[number];else{snprintf(temporary,sizeof(temporary),"REG_0x%x",number);message=temporary;}}
    else message=code>=0&&code<=16?messages[code]:"unknown regex error";
    size_t required=strlen(message)+1;if(size&&buffer){size_t copy=required<size?required:size;memcpy(buffer,message,copy-1);buffer[copy-1]=0;}return required;
}
