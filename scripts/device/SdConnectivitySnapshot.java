import android.net.*;
import java.io.IOException;
import java.net.InetAddress;
import java.net.Inet6Address;
import java.util.*;
import org.json.*;

/** Immutable projection of a complete, read-only host snapshot. No network I/O. */
final class SdConnectivitySnapshot {
    static final class Link {
        final int id,index,type;final String name;final boolean meteredKnown,metered;
        final Network network;final LinkProperties properties;final NetworkCapabilities capabilities;
        Link(int id,int index,String name,int type,LinkProperties lp,NetworkCapabilities nc,boolean known,boolean metered){
            this.id=id;this.index=index;this.name=name;this.type=type;this.network=new Network(id);
            properties=new LinkProperties(lp);capabilities=new NetworkCapabilities(nc);meteredKnown=known;this.metered=metered;
        }
        NetworkInfo info(){
            String label=type==ConnectivityManager.TYPE_WIFI?"WIFI":type==ConnectivityManager.TYPE_MOBILE?"MOBILE":type==ConnectivityManager.TYPE_ETHERNET?"ETHERNET":"UNKNOWN";
            NetworkInfo v=new NetworkInfo(type,0,label,"");v.setIsAvailable(true);v.setDetailedState(capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_SUSPENDED)?NetworkInfo.DetailedState.CONNECTED:NetworkInfo.DetailedState.SUSPENDED,null,name);return v;
        }
    }
    static final class Identities {
        private Map<String,Integer> current=new HashMap<String,Integer>();
        private Set<Integer> used=new HashSet<Integer>();private int next=1000000;
        synchronized Map<String,Integer> assign(Map<String,Integer> requested)throws IOException{
            Map<String,Integer> result=new HashMap<String,Integer>();Set<Integer> nextUsed=new HashSet<Integer>(used);int candidate=next;
            for(String key:new TreeSet<String>(requested.keySet())){
                Integer old=current.get(key);if(old!=null){result.put(key,old);continue;}
                int id=requested.get(key);
                if(id<=0||nextUsed.contains(id)){
                    while(candidate>0&&nextUsed.contains(candidate))candidate++;
                    if(candidate<=0||candidate==Integer.MAX_VALUE)throw new IOException("Network identity exhausted");id=candidate++;
                }
                nextUsed.add(id);result.put(key,id);
            }
            current=result;used=nextUsed;next=candidate;return new HashMap<String,Integer>(result);
        }
    }
    final Map<Integer,Link> links;final Integer active;final String namespace,resolverStatus;
    SdConnectivitySnapshot(Map<Integer,Link>links,Integer active,String namespace,String resolverStatus){
        this.links=Collections.unmodifiableMap(new LinkedHashMap<Integer,Link>(links));this.active=active;this.namespace=namespace;this.resolverStatus=resolverStatus;
    }
    Link activeLink(){return active==null?null:links.get(active);}
    private static InetAddress numeric(String text,int index)throws Exception{
        InetAddress a=NetworkUtils.numericToInetAddress(text);
        if(a instanceof Inet6Address&&a.isLinkLocalAddress())return Inet6Address.getByAddress(null,a.getAddress(),index);
        return a;
    }
    private static JSONArray bounded(JSONObject o,String key,int limit)throws Exception{
        JSONArray a=o.getJSONArray(key);if(a.length()>limit)throw new IOException("Host "+key+" limit");return a;
    }
    private static final class Draft {
        int index,type,id;String key,name;boolean known,metered;LinkProperties lp=new LinkProperties();NetworkCapabilities caps=new NetworkCapabilities();
    }
    static SdConnectivitySnapshot parse(String json,Identities identities)throws IOException{
        try{
            if(json.length()>262144)throw new IOException("Host snapshot size limit");JSONObject root=new JSONObject(json);
            if(root.getInt("schema")!=1||!root.getBoolean("complete"))throw new IOException("Incomplete host network snapshot");
            String namespace=root.getString("netns");if(!namespace.matches("net:\\[[0-9]+\\]"))throw new IOException("Host network namespace missing");
            JSONArray la=bounded(root,"links",256),aa=bounded(root,"addresses",1024),ra=bounded(root,"routes",4096),rules=bounded(root,"rules",256);
            Map<Integer,JSONObject> rawLinks=new TreeMap<Integer,JSONObject>();
            for(int i=0;i<la.length();i++){
                JSONObject l=la.getJSONObject(i);int idx=l.getInt("index");String name=l.getString("name");
                if(idx<=0||name.length()==0||name.length()>=16||name.indexOf('/')>=0||rawLinks.put(idx,l)!=null)throw new IOException("Invalid/duplicate host interface");
            }
            // Only local/main/default table rules with no selectors are implemented.
            Map<Integer,Set<Integer>> seen=new HashMap<Integer,Set<Integer>>();
            for(int i=0;i<rules.length();i++){
                JSONObject r=rules.getJSONObject(i);int family=r.getInt("family"),table=r.getInt("table"),priority=r.getInt("priority");
                if(family!=2&&family!=10)continue;
                if(r.getInt("action")!=1||r.getBoolean("selectors")||!((table==255&&priority==0)||(table==254&&priority==32766)||(table==253&&priority==32767)))
                    throw new IOException("Unsupported host routing policy");
                Set<Integer>s=seen.get(family);if(s==null){s=new HashSet<Integer>();seen.put(family,s);}if(!s.add(table))throw new IOException("Duplicate host routing policy");
            }
            if(!seen.containsKey(2)||!seen.get(2).containsAll(Arrays.asList(255,254)))throw new IOException("IPv4 routing policy unavailable");
            if(seen.containsKey(10)&&!seen.get(10).containsAll(Arrays.asList(255,254)))throw new IOException("IPv6 routing policy unavailable");
            Map<Integer,List<JSONObject>> addresses=new HashMap<Integer,List<JSONObject>>();
            for(int i=0;i<aa.length();i++){
                JSONObject a=aa.getJSONObject(i);int index=a.getInt("index"),flags=a.getInt("flags");if(!rawLinks.containsKey(index))throw new IOException("Inconsistent interface/address dump");
                if((flags&(0x40|0x08))!=0)continue; // Tentative/DAD-failed addresses are not usable.
                List<JSONObject>v=addresses.get(index);if(v==null){v=new ArrayList<JSONObject>();addresses.put(index,v);}v.add(a);
            }
            JSONObject serviceRoot=root.getJSONObject("services");JSONArray services=bounded(serviceRoot,"values",128);
            Map<Integer,Draft>drafts=new TreeMap<Integer,Draft>();
            for(Map.Entry<Integer,JSONObject>entry:rawLinks.entrySet()){
                int index=entry.getKey();JSONObject raw=entry.getValue();int flags=raw.getInt("flags");
                int operstate=raw.getInt("operstate"),carrier=raw.getInt("carrier");
                if((flags&1)==0||(flags&8)!=0||!addresses.containsKey(index)||carrier==0||operstate==1||operstate==2||operstate==3)continue;
                Draft d=new Draft();d.index=index;d.name=raw.getString("name");d.key=namespace+"/"+index+"/"+d.name;d.lp.setInterfaceName(d.name);d.lp.setMtu(raw.getInt("mtu"));
                List<String>addressValues=new ArrayList<String>();for(JSONObject a:addresses.get(index))addressValues.add(a.getString("address")+"/"+a.getInt("prefix"));Collections.sort(addressValues);
                for(String value:addressValues){int slash=value.lastIndexOf('/');d.lp.addLinkAddress(new LinkAddress(numeric(value.substring(0,slash),index),Integer.parseInt(value.substring(slash+1))));}
                JSONObject service=null;int matches=0;
                if(serviceRoot.getString("status").equals("read"))for(int i=0;i<services.length();i++){
                    JSONObject s=services.getJSONObject(i);String state=s.getString("state");if(s.getString("interface").equals(d.name)&&(state.equals("ready")||state.equals("online"))){service=s;matches++;}
                }
                if(matches!=1)service=null;
                String type=service==null?"":service.getString("type");
                d.type=raw.getBoolean("tunnel")?ConnectivityManager.TYPE_NONE:type.equals("wifi")||raw.getBoolean("wireless")?ConnectivityManager.TYPE_WIFI:type.equals("cellular")?ConnectivityManager.TYPE_MOBILE:
                    (type.equals("ethernet")||(raw.getInt("type")==1&&raw.getBoolean("physical")))?ConnectivityManager.TYPE_ETHERNET:ConnectivityManager.TYPE_NONE;
                d.caps.clearAll();
                if(d.type==ConnectivityManager.TYPE_WIFI)d.caps.addTransportType(NetworkCapabilities.TRANSPORT_WIFI);
                if(d.type==ConnectivityManager.TYPE_MOBILE)d.caps.addTransportType(NetworkCapabilities.TRANSPORT_CELLULAR);
                if(d.type==ConnectivityManager.TYPE_ETHERNET)d.caps.addTransportType(NetworkCapabilities.TRANSPORT_ETHERNET);
                // Explicit adapter policy for its supported host-managed physical links.
                // TRUSTED here does not mean validated Internet or a trusted TLS endpoint.
                if(d.type!=ConnectivityManager.TYPE_NONE){
                    d.caps.addCapability(NetworkCapabilities.NET_CAPABILITY_TRUSTED);
                    d.caps.addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_RESTRICTED);
                    d.caps.addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN);
                    d.caps.addCapability(NetworkCapabilities.NET_CAPABILITY_FOREGROUND);
                }
                if(raw.getInt("operstate")==6&&raw.getInt("carrier")==1)d.caps.addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_SUSPENDED);
                if(service!=null){
                    d.known=service.getBoolean("meteredKnown");d.metered=service.getBoolean("metered");
                    if(d.known&&!d.metered)d.caps.addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED);
                    JSONArray dns=bounded(service,"nameservers",64);for(int j=0;j<dns.length();j++)d.lp.addDnsServer(numeric(dns.getString(j),index));
                    JSONArray domains=bounded(service,"domains",64);List<String>names=new ArrayList<String>();
                    for(int j=0;j<domains.length();j++){String domain=domains.getString(j);if(!domain.matches("[A-Za-z0-9_.-]{1,255}"))throw new IOException("Unsupported DNS search domain");names.add(domain);}
                    if(!names.isEmpty())d.lp.setDomains(String.join(" ",names));
                }
                drafts.put(index,d);
            }
            Map<Integer,Integer>defaultIndex=new HashMap<Integer,Integer>(),bestMetric=new HashMap<Integer,Integer>(),bestTable=new HashMap<Integer,Integer>();
            List<JSONObject>orderedRoutes=new ArrayList<JSONObject>();for(int i=0;i<ra.length();i++)orderedRoutes.add(ra.getJSONObject(i));
            Collections.sort(orderedRoutes,new Comparator<JSONObject>(){public int compare(JSONObject a,JSONObject b){return a.toString().compareTo(b.toString());}});
            for(JSONObject r:orderedRoutes){
                int family=r.getInt("family"),table=r.getInt("table");if(family!=2&&family!=10)continue;
                if(table!=254&&table!=253)continue;
                if(r.getBoolean("multipath")||r.getInt("sourcePrefix")!=0||r.getInt("tos")!=0)throw new IOException("Unsupported host route selection");
                int kind=r.getInt("type"),index=r.getInt("oif"),prefix=r.getInt("prefix");Draft d=drafts.get(index);
                if(d!=null&&(kind==1||kind==7||kind==9)){
                    String destination=r.getString("destination");if(destination.length()==0)destination=family==2?"0.0.0.0":"::";
                    String gateway=r.getString("gateway");d.lp.addRoute(new RouteInfo(new IpPrefix(numeric(destination,index),prefix),gateway.length()==0?null:numeric(gateway,index),d.name,kind));
                }
                if(prefix!=0)continue;
                // Unsupported blocking/default forms prevent a guessed usable default.
                if(kind!=1||!rawLinks.containsKey(index))throw new IOException("Unsupported or inconsistent host default route");
                int rank=table==254?0:1,metric=r.getInt("metric");if(metric<0)throw new IOException("Unsupported route metric");
                if(!bestTable.containsKey(family)||rank<bestTable.get(family)||(rank==bestTable.get(family)&&metric<bestMetric.get(family))){bestTable.put(family,rank);bestMetric.put(family,metric);defaultIndex.put(family,index);}
                else if(rank==bestTable.get(family)&&metric==bestMetric.get(family)&&index!=defaultIndex.get(family))throw new IOException("Ambiguous equal-cost default routes");
            }
            // Rank even down-link routes before selecting a usable result. Never guess that
            // the kernel falls back to a higher metric when the lower route's link is down.
            Set<Integer>defaults=new HashSet<Integer>();for(Integer index:defaultIndex.values())if(drafts.containsKey(index))defaults.add(index);
            if(defaults.size()>1)throw new IOException("Split-family host defaults unsupported");
            Integer selected=defaults.isEmpty()?null:defaults.iterator().next();
            if(selected!=null){Draft d=drafts.get(selected);if(d.type==ConnectivityManager.TYPE_NONE)throw new IOException("Unsupported default link transport");d.caps.addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);}
            Map<String,Integer>wanted=new HashMap<String,Integer>();for(Draft d:drafts.values())wanted.put(d.key,d.index);
            Map<String,Integer>ids=identities.assign(wanted);Map<Integer,Link>result=new LinkedHashMap<Integer,Link>();Integer active=null;
            for(Draft d:drafts.values()){d.id=ids.get(d.key);result.put(d.id,new Link(d.id,d.index,d.name,d.type,d.lp,d.caps,d.known,d.metered));if(selected!=null&&selected==d.index)active=d.id;}
            return new SdConnectivitySnapshot(result,active,namespace,root.getJSONObject("resolver").getString("status"));
        }catch(IOException e){throw e;}catch(Exception e){throw new IOException("Invalid host network snapshot",e);}
    }
}
