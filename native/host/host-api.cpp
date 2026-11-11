#include "host-common.hpp"
#include <dlfcn.h>
#include <jni.h>
static std::string text(JNIEnv *e, jstring v) {
  if (!v)
    throw std::runtime_error("Missing API argument");
  const char *s = e->GetStringUTFChars(v, nullptr);
  if (!s)
    throw std::runtime_error("Invalid API argument");
  std::string r = s;
  e->ReleaseStringUTFChars(v, s);
  return r;
}
static GDBusConnection *session() {
  GError *e = nullptr;
  auto c = g_bus_get_sync(G_BUS_TYPE_SESSION, nullptr, &e);
  if (!c) {
    std::string msg = e ? e->message : "Session bus unavailable";
    g_clear_error(&e);
    throw std::runtime_error(msg);
  }
  return c;
}
static void error(JNIEnv *e, const std::exception &ex) {
  if (!e->ExceptionCheck())
    e->ThrowNew(e->FindClass("java/lang/IllegalStateException"), ex.what());
}
extern "C" JNIEXPORT void JNICALL
Java_org_saildroid_host_HostApi_openApplication(JNIEnv *e, jclass,
                                                jstring value) {
  try {
    auto s = text(e, value);
    auto c = session();
    auto v = call(c, "OpenApplication", g_variant_new("(s)", s.c_str()));
    g_variant_unref(v);
    g_object_unref(c);
  } catch (const std::exception &ex) {
    error(e, ex);
  }
}
extern "C" JNIEXPORT void JNICALL Java_org_saildroid_host_HostApi_startService(
    JNIEnv *e, jclass, jstring package, jstring service, jstring process) {
  try {
    auto a = text(e, package), b = text(e, service), d = text(e, process);
    auto c = session();
    auto v = call(c, "StartService",
                  g_variant_new("(sss)", a.c_str(), b.c_str(), d.c_str()));
    g_variant_unref(v);
    g_object_unref(c);
  } catch (const std::exception &ex) {
    error(e, ex);
  }
}
extern "C" JNIEXPORT jstring JNICALL
Java_org_saildroid_host_HostApi_state(JNIEnv *e, jclass, jstring package) {
  try {
    auto s = text(e, package);
    auto c = session();
    auto v = call(c, "GetState", g_variant_new("(s)", s.c_str()));
    const char *reply;
    g_variant_get(v, "(&s)", &reply);
    jstring result = e->NewStringUTF(reply);
    g_variant_unref(v);
    g_object_unref(c);
    return result;
  } catch (const std::exception &ex) {
    error(e, ex);
    return nullptr;
  }
}
extern "C" JNIEXPORT void JNICALL
Java_org_saildroid_host_HostApi_startActivityProcess(
    JNIEnv *e, jclass, jstring package, jstring activity, jstring process) {
  try {
    auto a = text(e, package), b = text(e, activity), d = text(e, process);
    auto c = session();
    auto v = call(c, "StartActivityProcess",
                  g_variant_new("(sss)", a.c_str(), b.c_str(), d.c_str()));
    g_variant_unref(v);
    g_object_unref(c);
  } catch (const std::exception &ex) {
    error(e, ex);
  }
}
extern "C" JNIEXPORT void JNICALL
Java_org_saildroid_host_HostApi_startProviderProcess(
    JNIEnv *e, jclass, jstring package, jstring provider, jstring process) {
  try {
    auto a = text(e, package), b = text(e, provider), d = text(e, process);
    auto c = session();
    auto v = call(c, "StartProviderProcess",
                  g_variant_new("(sss)", a.c_str(), b.c_str(), d.c_str()));
    g_variant_unref(v);
    g_object_unref(c);
  } catch (const std::exception &ex) {
    error(e, ex);
  }
}
extern "C" JNIEXPORT void JNICALL
Java_org_saildroid_host_HostApi_activateSelf(JNIEnv *e, jclass) {
  try {
    const char *key = getenv("SAILDROID_HOST_INSTANCE");
    const char *generation = getenv("SAILDROID_HOST_LAUNCH_ID");
    if (!key || !generation)
      throw std::runtime_error("Host generation is unavailable");
    auto c = session();
    auto mapped = call(c, "WindowEvent", g_variant_new("(ssi)", key, "mapped", 1));
    g_variant_unref(mapped);
    auto v = call(c, "Activate", g_variant_new("(ss)", key, generation));
    g_variant_unref(v);
    g_object_unref(c);
  } catch (const std::exception &ex) {
    error(e, ex);
  }
}
static GVariant *mce(const std::string &method) {
  if (method != "get_display_status" && method != "get_tklock_mode" &&
      method != "get_psm_state")
    throw std::runtime_error("MCE method is not read-only");
  GError *e = nullptr;
  auto c = g_bus_get_sync(G_BUS_TYPE_SYSTEM, nullptr, &e);
  if (!c) {
    g_clear_error(&e);
    throw std::runtime_error("System bus unavailable");
  }
  auto r = g_dbus_connection_call_sync(
      c, "com.nokia.mce", "/com/nokia/mce/request", "com.nokia.mce.request",
      method.c_str(), nullptr, nullptr, G_DBUS_CALL_FLAGS_NONE, 1000, nullptr,
      &e);
  g_object_unref(c);
  if (!r) {
    std::string s = e ? e->message : "MCE request failed";
    g_clear_error(&e);
    throw std::runtime_error(s);
  }
  return r;
}
static GDBusConnection *wake_lock_bus() {
  static GDBusConnection *bus = [] {
    GError *failure = nullptr;
    auto *value = g_bus_get_sync(G_BUS_TYPE_SYSTEM, nullptr, &failure);
    if (!value) {
      std::string message = failure ? failure->message : "Wake lock bus unavailable";
      g_clear_error(&failure);
      throw std::runtime_error(message);
    }
    return value;
  }();
  return bus;
}
static GVariant *wake_lock_request(const char *method, GVariant *arguments,
                                  const GVariantType *type) {
  GError *failure = nullptr;
  auto *reply = g_dbus_connection_call_sync(
      wake_lock_bus(), "com.nokia.mce", "/com/nokia/mce/request",
      "com.nokia.mce.request", method, arguments, type,
      G_DBUS_CALL_FLAGS_NONE, 1000, nullptr, &failure);
  if (!reply) {
    std::string message = failure ? failure->message : "MCE wake lock request failed";
    g_clear_error(&failure);
    throw std::runtime_error(message);
  }
  return reply;
}
static void wake_lock_session(const char *method, const std::string &session) {
  auto *reply = wake_lock_request(method, g_variant_new("(s)", session.c_str()), G_VARIANT_TYPE("(b)"));
  gboolean accepted = false;
  g_variant_get(reply, "(b)", &accepted);
  g_variant_unref(reply);
  if (!accepted) throw std::runtime_error("MCE wake lock session rejected");
}
static void wake_lock_screen(const char *method) {
  auto *reply = wake_lock_request(method, nullptr, G_VARIANT_TYPE_UNIT);
  g_variant_unref(reply);
}
extern "C" JNIEXPORT jint JNICALL
Java_org_saildroid_host_HostApi_acquireWakeLock(JNIEnv *env, jclass,
                                             jstring value, jboolean screen,
                                             jboolean renewing) {
  std::string session;
  bool started = false;
  try {
    session = text(env, value);
    auto *reply = wake_lock_request("req_cpu_keepalive_period", g_variant_new("(s)", session.c_str()), G_VARIANT_TYPE("(i)"));
    gint32 period = 0;
    g_variant_get(reply, "(i)", &period);
    g_variant_unref(reply);
    if (period <= 0) throw std::runtime_error("MCE wake lock period unavailable");
    wake_lock_session("req_cpu_keepalive_start", session);
    started = true;
    if (screen) wake_lock_screen("req_display_blanking_pause");
    return period;
  } catch (const std::exception &failure) {
    if (started && !renewing) {
      try { wake_lock_session("req_cpu_keepalive_stop", session); }
      catch (const std::exception &cleanup) {
        fprintf(stderr, "SDPOWER=wake_lock_cleanup_failed|reason=%s\n", cleanup.what());
      }
    }
    error(env, failure);
    return 0;
  }
}
extern "C" JNIEXPORT void JNICALL
Java_org_saildroid_host_HostApi_releaseWakeLock(JNIEnv *env, jclass,
                                             jstring value, jboolean cancel_screen) {
  try {
    std::string session = text(env, value);
    if (cancel_screen) wake_lock_screen("req_display_cancel_blanking_pause");
    wake_lock_session("req_cpu_keepalive_stop", session);
  } catch (const std::exception &failure) {
    error(env, failure);
  }
}
extern "C" JNIEXPORT jstring JNICALL
Java_org_saildroid_host_HostApi_mceString(JNIEnv *e, jclass, jstring method) {
  try {
    auto v = mce(text(e, method));
    if (!g_variant_is_of_type(v, G_VARIANT_TYPE("(s)"))) {
      g_variant_unref(v);
      throw std::runtime_error("MCE string type differs");
    }
    const char *s;
    g_variant_get(v, "(&s)", &s);
    auto result = e->NewStringUTF(s);
    g_variant_unref(v);
    return result;
  } catch (const std::exception &ex) {
    error(e, ex);
    return nullptr;
  }
}
extern "C" JNIEXPORT jboolean JNICALL
Java_org_saildroid_host_HostApi_mceBoolean(JNIEnv *e, jclass, jstring method) {
  try {
    auto v = mce(text(e, method));
    if (!g_variant_is_of_type(v, G_VARIANT_TYPE("(b)"))) {
      g_variant_unref(v);
      throw std::runtime_error("MCE boolean type differs");
    }
    gboolean b;
    g_variant_get(v, "(b)", &b);
    g_variant_unref(v);
    return b ? JNI_TRUE : JNI_FALSE;
  } catch (const std::exception &ex) {
    error(e, ex);
    return JNI_FALSE;
  }
}

extern "C" JNIEXPORT void JNICALL
Java_org_saildroid_host_HostApi_ready(JNIEnv *e, jclass) {
  try {
    auto ready = (void (*)(void))dlsym(RTLD_DEFAULT, "sd_host_java_ready");
    if (!ready)
      throw std::runtime_error("Native host lifecycle unavailable");
    ready();
  } catch (const std::exception &ex) {
    error(e, ex);
  }
}

// Fixed read-only DSME endpoint. Failure is propagated, never reported as normal.
extern "C" JNIEXPORT jstring JNICALL
Java_org_saildroid_host_HostApi_thermalState(JNIEnv *e, jclass) {
  try {
    GError *failure = nullptr;
    auto c = g_bus_get_sync(G_BUS_TYPE_SYSTEM, nullptr, &failure);
    if (!c) {
      std::string message = failure ? failure->message : "System bus unavailable";
      g_clear_error(&failure);
      throw std::runtime_error(message);
    }
    auto v = g_dbus_connection_call_sync(
        c, "com.nokia.thermalmanager", "/com/nokia/thermalmanager",
        "com.nokia.thermalmanager", "get_thermal_state", nullptr,
        G_VARIANT_TYPE("(s)"), G_DBUS_CALL_FLAGS_NONE, 1000, nullptr, &failure);
    g_object_unref(c);
    if (!v) {
      std::string message = failure ? failure->message : "DSME thermal request failed";
      g_clear_error(&failure);
      throw std::runtime_error(message);
    }
    const char *state;
    g_variant_get(v, "(&s)", &state);
    auto result = e->NewStringUTF(state);
    g_variant_unref(v);
    return result;
  } catch (const std::exception &ex) {
    error(e, ex);
    return nullptr;
  }
}
