#include "host-common.hpp"
#include <cctype>
#include <jni.h>
#include <linux/genetlink.h>
#include <linux/netlink.h>
#include <linux/nl80211.h>
#include <poll.h>
#include <functional>
#include <vector>

namespace {
using AttributeVisitor=std::function<void(unsigned,const char *,size_t)>;

void wifi_attributes(const char *data,size_t size,const AttributeVisitor &visit) {
    while(size>=NLA_HDRLEN){
        nlattr header;memcpy(&header,data,sizeof(header));
        if(header.nla_len<NLA_HDRLEN||header.nla_len>size)
            throw std::runtime_error("Malformed Wi-Fi netlink attribute");
        visit(header.nla_type&NLA_TYPE_MASK,data+NLA_HDRLEN,header.nla_len-NLA_HDRLEN);
        size_t step=NLA_ALIGN(header.nla_len);
        if(step>size){
            if(header.nla_len==size)return;
            throw std::runtime_error("Malformed Wi-Fi netlink padding");
        }
        data+=step;size-=step;
    }
    if(size)throw std::runtime_error("Truncated Wi-Fi netlink attribute");
}

template<typename T> T wifi_number(const char *data,size_t size) {
    if(size!=sizeof(T))throw std::runtime_error("Invalid Wi-Fi netlink value");
    T value;memcpy(&value,data,sizeof(value));return value;
}

// One bounded, read-only generic-netlink exchange. The socket is private to
// the query, and responses must come from the kernel with our sequence ID.
void wifi_query(int socket,unsigned sequence,unsigned family,unsigned command,
                bool dump,unsigned attribute,const std::string &value,
                const AttributeVisitor &visit) {
    size_t attribute_size=NLA_HDRLEN+value.size();
    std::vector<char> request(NLMSG_HDRLEN+GENL_HDRLEN+NLA_ALIGN(attribute_size));
    nlmsghdr header={};header.nlmsg_len=request.size();header.nlmsg_type=family;
    header.nlmsg_flags=NLM_F_REQUEST|(dump?NLM_F_DUMP:0);header.nlmsg_seq=sequence;
    genlmsghdr generic={};generic.cmd=command;generic.version=1;
    nlattr field={};field.nla_len=attribute_size;field.nla_type=attribute;
    memcpy(request.data(),&header,sizeof(header));
    memcpy(request.data()+NLMSG_HDRLEN,&generic,sizeof(generic));
    memcpy(request.data()+NLMSG_HDRLEN+GENL_HDRLEN,&field,sizeof(field));
    memcpy(request.data()+NLMSG_HDRLEN+GENL_HDRLEN+NLA_HDRLEN,value.data(),value.size());
    sockaddr_nl kernel={};kernel.nl_family=AF_NETLINK;
    if(sendto(socket,request.data(),request.size(),0,reinterpret_cast<sockaddr *>(&kernel),sizeof(kernel))!=static_cast<ssize_t>(request.size()))
        throw std::runtime_error("Cannot send Wi-Fi capability query");
    auto deadline=std::chrono::steady_clock::now()+std::chrono::milliseconds(1500);
    std::vector<char> buffer(262144);
    for(unsigned packet=0;packet<64;packet++){
        auto remaining=std::chrono::duration_cast<std::chrono::milliseconds>(deadline-std::chrono::steady_clock::now()).count();
        pollfd ready={socket,POLLIN,0};
        if(remaining<=0||poll(&ready,1,remaining)<=0)
            throw std::runtime_error("Wi-Fi capability query timed out");
        sockaddr_nl sender={};iovec bytes={buffer.data(),buffer.size()};
        msghdr message={};message.msg_name=&sender;message.msg_namelen=sizeof(sender);
        message.msg_iov=&bytes;message.msg_iovlen=1;
        ssize_t received=recvmsg(socket,&message,0);
        if(received<=0||(message.msg_flags&MSG_TRUNC)||sender.nl_pid!=0)
            throw std::runtime_error("Invalid Wi-Fi capability response");
        size_t offset=0;bool replied=false;
        while(offset+NLMSG_HDRLEN<=static_cast<size_t>(received)){
            nlmsghdr response;memcpy(&response,buffer.data()+offset,sizeof(response));
            if(response.nlmsg_len<NLMSG_HDRLEN||offset+response.nlmsg_len>static_cast<size_t>(received))
                throw std::runtime_error("Malformed Wi-Fi capability message");
            const char *payload=buffer.data()+offset+NLMSG_HDRLEN;
            size_t size=response.nlmsg_len-NLMSG_HDRLEN;offset+=NLMSG_ALIGN(response.nlmsg_len);
            if(response.nlmsg_seq!=sequence)continue;
            if(response.nlmsg_flags&NLM_F_DUMP_INTR)throw std::runtime_error("Wi-Fi capability dump interrupted");
            if(response.nlmsg_type==NLMSG_ERROR){
                if(size<sizeof(nlmsgerr))throw std::runtime_error("Truncated Wi-Fi netlink error");
                nlmsgerr error;memcpy(&error,payload,sizeof(error));
                if(error.error)throw std::runtime_error("Wi-Fi capability query rejected");
                continue;
            }
            if(response.nlmsg_type==NLMSG_DONE){
                if(size>=sizeof(int)&&wifi_number<int>(payload,sizeof(int))!=0)
                    throw std::runtime_error("Wi-Fi capability dump failed");
                return;
            }
            if(response.nlmsg_type!=family||size<GENL_HDRLEN)
                throw std::runtime_error("Unexpected Wi-Fi capability message");
            wifi_attributes(payload+GENL_HDRLEN,size-GENL_HDRLEN,visit);replied=true;
        }
        if(!dump&&replied)return;
    }
    throw std::runtime_error("Wi-Fi capability response exceeds limit");
}

int wifi_features(int socket) {
    unsigned family=0;bool station=false,band5=false,phy=false;
    wifi_query(socket,1,GENL_ID_CTRL,CTRL_CMD_GETFAMILY,false,CTRL_ATTR_FAMILY_NAME,
               std::string("nl80211\0",8),[&](unsigned kind,const char *data,size_t size){
        if(kind==CTRL_ATTR_FAMILY_ID)family=wifi_number<uint16_t>(data,size);
    });
    if(!family)throw std::runtime_error("Host nl80211 family unavailable");
    wifi_query(socket,2,family,NL80211_CMD_GET_WIPHY,true,NL80211_ATTR_SPLIT_WIPHY_DUMP,"",
               [&](unsigned kind,const char *data,size_t size){
        if(kind==NL80211_ATTR_WIPHY){wifi_number<uint32_t>(data,size);phy=true;}
        if(kind==NL80211_ATTR_SUPPORTED_IFTYPES)wifi_attributes(data,size,[&](unsigned type,const char *,size_t){
            if(type==NL80211_IFTYPE_STATION)station=true;
        });
        if(kind==NL80211_ATTR_WIPHY_BANDS)wifi_attributes(data,size,[&](unsigned,const char *band,size_t band_size){
            wifi_attributes(band,band_size,[&](unsigned type,const char *frequencies,size_t frequencies_size){
                if(type!=NL80211_BAND_ATTR_FREQS)return;
                wifi_attributes(frequencies,frequencies_size,[&](unsigned,const char *frequency,size_t frequency_size){
                    wifi_attributes(frequency,frequency_size,[&](unsigned field,const char *number,size_t number_size){
                        if(field!=NL80211_FREQUENCY_ATTR_FREQ)return;
                        uint32_t mhz=wifi_number<uint32_t>(number,number_size);
                        if(mhz>=5000&&mhz<6000)band5=true;
                    });
                });
            });
        });
    });
    if(!phy)throw std::runtime_error("Host Wi-Fi physical capabilities unavailable");
    // Android's INFRA and INFRA_5G bits. Other features also require matching
    // adapter APIs, so this read-only backend does not advertise them.
    return (station?1:0)|(station&&band5?2:0);
}
}

extern "C" JNIEXPORT jint JNICALL
Java_org_saildroid_host_HostApi_wifiSupportedFeatures(JNIEnv *env,jclass) {
    int socket=::socket(AF_NETLINK,SOCK_RAW|SOCK_CLOEXEC,NETLINK_GENERIC);
    if(socket<0){
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),"Host Wi-Fi netlink socket unavailable");
        return 0;
    }
    int features=0;
    try { features=wifi_features(socket); }
    catch(const std::exception &error){env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),error.what());}
    close(socket);return features;
}

// Query ConnMan's actual radio state. There is deliberately no setter, scan,
// network mutation, credential query or shell command on this boundary.
extern "C" JNIEXPORT jint JNICALL
Java_org_saildroid_host_HostApi_wifiEnabledState(JNIEnv *env,jclass) {
    GError *error=nullptr;
    auto bus=g_bus_get_sync(G_BUS_TYPE_SYSTEM,nullptr,&error);
    if(!bus){
        g_clear_error(&error);
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),"Host network bus unavailable");
        return 4;
    }
    auto reply=g_dbus_connection_call_sync(bus,"net.connman","/","net.connman.Manager",
            "GetTechnologies",nullptr,G_VARIANT_TYPE("(a(oa{sv}))"),
            G_DBUS_CALL_FLAGS_NONE,1500,nullptr,&error);
    g_object_unref(bus);
    if(!reply){
        g_clear_error(&error);
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),"Host Wi-Fi technology query unavailable");
        return 4;
    }
    auto technologies=g_variant_get_child_value(reply,0);
    GVariantIter iterator;g_variant_iter_init(&iterator,technologies);
    const char *path=nullptr;GVariant *properties=nullptr;
    int state=4,count=0;
    while(g_variant_iter_next(&iterator,"(&o@a{sv})",&path,&properties)){
        const char *type=nullptr;gboolean powered=false;
        if(g_variant_lookup(properties,"Type","&s",&type)&&!strcmp(type,"wifi")){
            count++;
            if(g_variant_lookup(properties,"Powered","b",&powered))state=powered?3:1;
        }
        g_variant_unref(properties);
    }
    g_variant_unref(technologies);g_variant_unref(reply);
    if(count!=1||state==4){
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),"Host Wi-Fi technology state is missing or ambiguous");
        return 4;
    }
    return state;
}

extern "C" JNIEXPORT jstring JNICALL
Java_org_saildroid_host_HostApi_wifiConnectionInfo(JNIEnv *env,jclass,jboolean include_name) {
    GError *error=nullptr;
    auto bus=g_bus_get_sync(G_BUS_TYPE_SYSTEM,nullptr,&error);
    if(!bus){
        g_clear_error(&error);
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),"Host network bus unavailable");
        return nullptr;
    }
    auto reply=g_dbus_connection_call_sync(bus,"net.connman","/","net.connman.Manager",
            "GetServices",nullptr,G_VARIANT_TYPE("(a(oa{sv}))"),
            G_DBUS_CALL_FLAGS_NONE,1500,nullptr,&error);
    g_object_unref(bus);
    if(!reply){
        g_clear_error(&error);
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),"Host Wi-Fi connection query unavailable");
        return nullptr;
    }
    Json snapshot={{"connected",false}};
    auto services=g_variant_get_child_value(reply,0);
    GVariantIter iterator;g_variant_iter_init(&iterator,services);
    const char *path=nullptr;GVariant *properties=nullptr;
    int connected=0;
    while(g_variant_iter_next(&iterator,"(&o@a{sv})",&path,&properties)){
        const char *type=nullptr,*state=nullptr;
        bool wifi=g_variant_lookup(properties,"Type","&s",&type)&&!strcmp(type,"wifi");
        bool active=g_variant_lookup(properties,"State","&s",&state)&&
                (!strcmp(state,"ready")||!strcmp(state,"online"));
        if(wifi&&active){
            connected++;
            snapshot["connected"]=true;
            const char *value=nullptr;
            if(include_name&&g_variant_lookup(properties,"Name","&s",&value))snapshot["name"]=value;
            auto ipv4=g_variant_lookup_value(properties,"IPv4",G_VARIANT_TYPE("a{sv}"));
            if(ipv4){
                for(const char *key:{"Address","Netmask","Gateway"}){
                    if(g_variant_lookup(ipv4,key,"&s",&value)){
                        std::string name=key;
                        name[0]=static_cast<char>(std::tolower(name[0]));
                        snapshot[name]=value;
                    }
                }
                g_variant_unref(ipv4);
            }
            auto dns=g_variant_lookup_value(properties,"Nameservers",G_VARIANT_TYPE("as"));
            if(dns){
                snapshot["dns"]=Json::array();
                GVariantIter names;g_variant_iter_init(&names,dns);
                while(g_variant_iter_next(&names,"&s",&value)){
                    auto address=g_inet_address_new_from_string(value);
                    if(address){
                        if(g_inet_address_get_family(address)==G_SOCKET_FAMILY_IPV4)snapshot["dns"].push_back(value);
                        g_object_unref(address);
                    }
                }
                g_variant_unref(dns);
            }
        }
        g_variant_unref(properties);
    }
    g_variant_unref(services);g_variant_unref(reply);
    if(connected>1){
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),"Host Wi-Fi connection is ambiguous");
        return nullptr;
    }
    // Serialize only selected connection fields. ConnMan's other properties
    // can contain saved credentials and must never cross this boundary.
    auto text=snapshot.dump(-1,' ',true);
    return env->NewStringUTF(text.c_str());
}
