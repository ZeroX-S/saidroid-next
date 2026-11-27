"""Private-table imports preserve real reader values and never invent readiness."""
from pathlib import Path
import ctypes, os, subprocess, tempfile

repo=Path(__file__).resolve().parents[3]
with tempfile.TemporaryDirectory(prefix='sd-hardware-property-') as directory:
    root=Path(directory)
    reader=root/'host.c'
    reader.write_text('''#include <stdlib.h>
#include <string.h>
int my_property_get(const char *key,char *out,const char *fallback){
 if(strcmp(key,"hwservicemanager.ready"))abort();
 const char *value=getenv("SD_PROPERTY_FIXTURE_VALUE");if(!value)value=fallback;
 strcpy(out,value);return strlen(out);
}
''')
    host=root/'host.so'
    subprocess.run(['gcc','-shared','-fPIC','-o',str(host),str(reader)],check=True)
    private_source=root/'private.c'
    private_source.write_text('''#include <string.h>
static int count;static char saved[92];
int bionic___system_property_set(const char *key,const char *value){
 if(strcmp(key,"hwservicemanager.ready"))return -1;
 count++;strcpy(saved,value);return 0;
}
int writes(void){return count;}const char *value(void){return saved;}
''')
    private=root/'private.so'
    subprocess.run(['gcc','-shared','-fPIC','-o',str(private),str(private_source)],check=True)
    helper=root/'helper.so'
    subprocess.run(['gcc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
                    '-DSD_HOST_PROPERTY_LIBRARY="'+str(host)+'"',
                    str(repo/'native/compat/runtime-hardware-properties.c'),'-o',str(helper),'-ldl'],check=True)
    state=ctypes.CDLL(str(private));state.value.restype=ctypes.c_char_p
    bridge=ctypes.CDLL(str(helper));read=bridge.sd_import_host_hardware_properties
    read.argtypes=[ctypes.c_void_p];read.restype=ctypes.c_int
    for value in ['true','false']:
        os.environ['SD_PROPERTY_FIXTURE_VALUE']=value
        assert read(state._handle)==1 and state.value()==value.encode()
    assert state.writes()==2
    for value in ['', 'invalid']:
        os.environ['SD_PROPERTY_FIXTURE_VALUE']=value
        assert read(state._handle)==0 and state.writes()==2 and state.value()==b'false'
    host.chmod(0o666)
    os.environ['SD_PROPERTY_FIXTURE_VALUE']='true'
    assert read(state._handle)==0 and state.writes()==2 and state.value()==b'false'
    print('HOST_HARDWARE_PROPERTY=PASS|true_and_false_preserved|absent_invalid_untrusted_rejected|private_table_only|no_host_setter')
