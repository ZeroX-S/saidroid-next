"""Truthful metadata for this Android compatibility component, not host claims."""
import json,re

def properties(text):
    result={}
    for line in text.splitlines():
        if not line or line.startswith('#'):continue
        key,separator,value=line.partition('=')
        assert separator and key and key==key.strip() and key not in result
        result[key]=value
    return result

def update_properties(text,runtime,source):
    spec=json.loads(source.read_text());assert spec['schema']=='saildroid-component-properties-v1'
    first=spec['first_supported_api'];assert type(first)is int and first==runtime['api']==29
    assert spec['preserve_existing_signing_tags']is True and spec['invent_android_partitions']is False and spec['certify_secure_host_build']is False
    values=properties(text);assert values['ro.build.version.sdk']==str(runtime['api'])
    assert 'ro.product.first_api_level'not in values or values['ro.product.first_api_level']==str(first)
    fields=['ro.product.brand','ro.product.name','ro.product.device','ro.build.version.release','ro.build.id','ro.build.version.incremental','ro.build.type','ro.build.tags']
    parts=[values[key]for key in fields]
    assert all(re.fullmatch(r'[A-Za-z0-9._,-]+',value)for value in parts)
    fingerprint='{}/{}/{}:{}/{}/{}:{}/{}'.format(*parts)
    assert len(fingerprint.encode())<92
    replacements={'ro.product.first_api_level':str(first),'ro.build.fingerprint':fingerprint}
    lines=[]
    for line in text.splitlines():
        key=line.partition('=')[0]
        lines.append(key+'='+replacements[key]if key in replacements else line)
    for key,value in replacements.items():
        if key not in values:lines.append(key+'='+value)
    updated='\n'.join(lines)+'\n';after=properties(updated)
    assert {k:v for k,v in values.items()if k not in replacements}=={k:v for k,v in after.items()if k not in replacements}
    assert after['ro.build.tags']==values['ro.build.tags']
    return updated,dict(schema=spec['schema'],first_supported_api=first,first_supported_api_scope=spec['first_supported_api_scope'],changed={key:dict(before=values.get(key),after=after[key])for key in replacements if values.get(key)!=after[key]},signing_tags_preserved=values['ro.build.tags'],android_partition_properties_added=False,secure_host_claimed=False)
