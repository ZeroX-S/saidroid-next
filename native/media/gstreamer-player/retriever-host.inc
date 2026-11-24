// MediaMetadataRetriever uses the same bounded appsrc and software decoders as
// MediaPlayer. Its pipeline remains paused and sends audio to a fakesink.
namespace retriever {
static jfieldID context;
struct State {
    std::mutex mutex;
    std::shared_ptr<Player> player;
    std::map<int, std::string> metadata;
    State() : player(std::make_shared<Player>(next_id++)) {}
};
static std::mutex mutex;
static std::map<long, std::shared_ptr<State>> states;

static std::shared_ptr<State> get_state(JNIEnv* env, jobject self) {
    long id = env->GetLongField(self, context);
    std::lock_guard<std::mutex> guard(mutex);
    auto found = states.find(id);
    if (found != states.end()) return found->second;
    fail(env, "java/lang/IllegalStateException", "MediaMetadataRetriever is released");
    return {};
}

static void setup(JNIEnv* env, jobject self) {
    auto state = std::make_shared<State>();
    long id = state->player->id;
    { std::lock_guard<std::mutex> guard(mutex); states[id] = state; }
    env->SetLongField(self, context, id);
    fprintf(stderr, "SDRETRIEVER=setup|id=%ld|backend=gstreamer\n", id);
}

static void release(JNIEnv* env, jobject self) {
    long id = env->GetLongField(self, context);
    env->SetLongField(self, context, 0);
    std::shared_ptr<State> state;
    {
        std::lock_guard<std::mutex> guard(mutex);
        auto found = states.find(id);
        if (found == states.end()) return;
        state = found->second;
        states.erase(found);
    }
    std::lock_guard<std::mutex> guard(state->mutex);
    state->player->shutdown();
    fprintf(stderr, "SDRETRIEVER=released|id=%ld\n", id);
}

static void tag(State& state, GstTagList* tags, const char* name, int key) {
    gchar* value = nullptr;
    if (tags && gst_tag_list_get_string(tags, name, &value)) {
        state.metadata[key] = value;
        g_free(value);
    }
}

static bool load(JNIEnv* env, State& state, const char* uri) {
    auto player = state.player;
    if (!configure(env, player, uri, true)) return false;
    GstStateChangeReturn result = gst_element_set_state(player->pipe, GST_STATE_PAUSED);
    if (result != GST_STATE_CHANGE_FAILURE)
        result = gst_element_get_state(player->pipe, nullptr, nullptr, 8 * GST_SECOND);
    if (result != GST_STATE_CHANGE_SUCCESS || player->error_sent) {
        player->shutdown();
        fail(env, "java/lang/IllegalArgumentException", "Cannot read media metadata within deadline");
        return false;
    }
    player->prepared = true;
    gint videos = 0, audios = 0;
    g_object_get(player->pipe, "n-video", &videos, "n-audio", &audios, nullptr);
    state.metadata[10] = std::to_string(videos + audios);
    if (videos) { state.metadata[17] = "yes"; state.metadata[24] = "0"; }
    if (audios) state.metadata[16] = "yes";
    gint64 duration = 0;
    if (gst_element_query_duration(player->pipe, GST_FORMAT_TIME, &duration) && duration >= 0)
        state.metadata[9] = std::to_string(duration / GST_MSECOND);
    for (int kind = 0; kind < 2; ++kind) {
        if (!(kind ? audios : videos)) continue;
        GstTagList* tags = nullptr;
        g_signal_emit_by_name(player->pipe, kind ? "get-audio-tags" : "get-video-tags", 0, &tags);
        tag(state, tags, GST_TAG_TITLE, 7);
        tag(state, tags, GST_TAG_ARTIST, 2);
        tag(state, tags, GST_TAG_ALBUM, 1);
        tag(state, tags, GST_TAG_GENRE, 6);
        guint bitrate = 0;
        if (tags && gst_tag_list_get_uint(tags, GST_TAG_BITRATE, &bitrate))
            state.metadata[20] = std::to_string(bitrate);
        gchar* orientation = nullptr;
        if (tags && gst_tag_list_get_string(tags, GST_TAG_IMAGE_ORIENTATION, &orientation)) {
            if (!strcmp(orientation, "rotate-0")) state.metadata[24] = "0";
            if (!strcmp(orientation, "rotate-90")) state.metadata[24] = "90";
            if (!strcmp(orientation, "rotate-180")) state.metadata[24] = "180";
            if (!strcmp(orientation, "rotate-270")) state.metadata[24] = "270";
            g_free(orientation);
        }
        if (tags) gst_tag_list_unref(tags);
    }
    if (videos) {
        GstSample* sample = gst_app_sink_try_pull_preroll(GST_APP_SINK(player->sink), GST_SECOND);
        GstVideoInfo info;
        if (sample && gst_video_info_from_caps(&info, gst_sample_get_caps(sample))) {
            state.metadata[18] = std::to_string(GST_VIDEO_INFO_WIDTH(&info));
            state.metadata[19] = std::to_string(GST_VIDEO_INFO_HEIGHT(&info));
            if (GST_VIDEO_INFO_FPS_D(&info))
                state.metadata[25] = std::to_string(double(GST_VIDEO_INFO_FPS_N(&info)) / GST_VIDEO_INFO_FPS_D(&info));
        }
        if (sample) gst_sample_unref(sample);
    }
    fprintf(stderr, "SDRETRIEVER=loaded|id=%ld|video=%d|audio=%d|keys=%zu\n",
            player->id, videos, audios, state.metadata.size());
    return true;
}

static void source_fd(JNIEnv* env, jobject self, jobject descriptor, jlong offset, jlong length) {
    auto state = get_state(env, self);
    if (!state) return;
    std::lock_guard<std::mutex> guard(state->mutex);
    auto player = std::make_shared<Player>(state->player->id);
    if (!descriptor) { fail(env, "java/lang/IllegalArgumentException", "Null media descriptor"); return; }
    jclass type = env->GetObjectClass(descriptor);
    int fd = env->GetIntField(descriptor, env->GetFieldID(type, "descriptor", "I"));
    env->DeleteLocalRef(type);
    struct stat info{};
    if (offset < 0 || length < 0 || fstat(fd, &info) || !S_ISREG(info.st_mode) || offset > info.st_size) {
        fail(env, "java/lang/IllegalArgumentException", "Invalid seekable media descriptor range");
        return;
    }
    player->fd = dup(fd);
    if (player->fd < 0) { fail(env, "java/lang/IllegalArgumentException", "Cannot retain media descriptor"); return; }
    player->offset = offset;
    player->length = std::min<int64_t>(length, info.st_size - offset);
    state->player->shutdown();
    state->player = player;
    state->metadata.clear();
    load(env, *state, "appsrc://");
}

static void source_callback(JNIEnv* env, jobject self, jobject source) {
    auto state = get_state(env, self);
    if (!state) return;
    std::lock_guard<std::mutex> guard(state->mutex);
    if (!source) { fail(env, "java/lang/IllegalArgumentException", "Null MediaDataSource"); return; }
    auto player = std::make_shared<Player>(state->player->id);
    jclass type = env->GetObjectClass(source);
    player->source_read = env->GetMethodID(type, "readAt", "(J[BII)I");
    player->source_size = env->GetMethodID(type, "getSize", "()J");
    player->source_close = env->GetMethodID(type, "close", "()V");
    env->DeleteLocalRef(type);
    if (env->ExceptionCheck()) return;
    player->java_source = env->NewGlobalRef(source);
    player->length = -1;
    state->player->shutdown();
    state->player = player;
    state->metadata.clear();
    load(env, *state, "appsrc://");
}

static void source_uri(JNIEnv* env, jobject self, jobject, jstring uri, jobjectArray keys, jobjectArray values) {
    auto state = get_state(env, self);
    if (!state) return;
    if (!uri) { fail(env, "java/lang/IllegalArgumentException", "Null media URI"); return; }
    const char* text = env->GetStringUTFChars(uri, nullptr);
    if (!text) return;
    bool http = !strncmp(text, "http://", 7) || !strncmp(text, "https://", 8);
    gchar* local = nullptr;
    if (!http) local = strstr(text, "://") ? g_strdup(text) : g_filename_to_uri(text, nullptr, nullptr);
    env->ReleaseStringUTFChars(uri, text);
    if (!http) {
        if (!local) { fail(env, "java/lang/IllegalArgumentException", "Invalid media URI"); return; }
        std::lock_guard<std::mutex> guard(state->mutex);
        long id = state->player->id;
        state->player->shutdown();
        state->player = std::make_shared<Player>(id);
        state->metadata.clear();
        load(env, *state, local);
        g_free(local);
        return;
    }
    jclass type = env->FindClass("SdMediaDataSource");
    if (!type) return;
    jmethodID constructor = env->GetMethodID(type, "<init>", "(Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;)V");
    jobject source = env->NewObject(type, constructor, uri, keys, values);
    if (source) { retriever::source_callback(env, self, source); env->DeleteLocalRef(source); }
    env->DeleteLocalRef(type);
}

static jstring metadata(JNIEnv* env, jobject self, jint key) {
    auto state = get_state(env, self);
    if (!state) return nullptr;
    std::lock_guard<std::mutex> guard(state->mutex);
    auto found = state->metadata.find(key);
    return found == state->metadata.end() ? nullptr : env->NewStringUTF(found->second.c_str());
}

static jobject frame(JNIEnv* env, jobject self, jlong time, jint option, jint width, jint height) {
    auto state = get_state(env, self);
    if (!state) return nullptr;
    std::lock_guard<std::mutex> guard(state->mutex);
    auto player = state->player;
    if (!player->prepared || !state->metadata.count(17)) return nullptr;
    if (time > INT64_MAX / GST_USECOND) return nullptr;
    GstSeekFlags flags = GstSeekFlags(GST_SEEK_FLAG_FLUSH | GST_SEEK_FLAG_KEY_UNIT);
    if (option == 0) flags = GstSeekFlags(flags | GST_SEEK_FLAG_SNAP_BEFORE);
    if (option == 1) flags = GstSeekFlags(flags | GST_SEEK_FLAG_SNAP_AFTER);
    if (option == 2) flags = GstSeekFlags(flags | GST_SEEK_FLAG_SNAP_NEAREST);
    if (option == 3) flags = GstSeekFlags(GST_SEEK_FLAG_FLUSH | GST_SEEK_FLAG_ACCURATE);
    if (!gst_element_seek_simple(player->pipe, GST_FORMAT_TIME, flags, std::max<jlong>(0, time) * GST_USECOND)) return nullptr;
    GstSample* sample = gst_app_sink_try_pull_preroll(GST_APP_SINK(player->sink), 8 * GST_SECOND);
    if (!sample) return nullptr;
    GstVideoInfo info;
    GstVideoFrame pixels;
    if (!gst_video_info_from_caps(&info, gst_sample_get_caps(sample)) ||
            !gst_video_frame_map(&pixels, &info, gst_sample_get_buffer(sample), GST_MAP_READ)) {
        gst_sample_unref(sample);
        return nullptr;
    }
    int source_width = GST_VIDEO_INFO_WIDTH(&info), source_height = GST_VIDEO_INFO_HEIGHT(&info);
    if (source_width <= 0 || source_height <= 0 || int64_t(source_width) * source_height > 16777216) {
        gst_video_frame_unmap(&pixels);
        gst_sample_unref(sample);
        return nullptr;
    }
    jclass bitmap = env->FindClass("android/graphics/Bitmap");
    jclass config = env->FindClass("android/graphics/Bitmap$Config");
    jobject argb = env->GetStaticObjectField(config, env->GetStaticFieldID(config, "ARGB_8888", "Landroid/graphics/Bitmap$Config;"));
    jintArray colors = env->NewIntArray(source_width * source_height);
    if (colors) {
        std::vector<jint> row(source_width);
        for (int y = 0; y < source_height; ++y) {
            const unsigned char* data = static_cast<const unsigned char*>(GST_VIDEO_FRAME_PLANE_DATA(&pixels, 0)) + y * GST_VIDEO_FRAME_PLANE_STRIDE(&pixels, 0);
            for (int x = 0; x < source_width; ++x)
                row[x] = jint(0xff000000u | (data[x * 4] << 16) | (data[x * 4 + 1] << 8) | data[x * 4 + 2]);
            env->SetIntArrayRegion(colors, y * source_width, source_width, row.data());
        }
    }
    gst_video_frame_unmap(&pixels);
    gst_sample_unref(sample);
    jobject result = nullptr;
    if (colors && !env->ExceptionCheck())
        result = env->CallStaticObjectMethod(bitmap, env->GetStaticMethodID(bitmap, "createBitmap", "([IIILandroid/graphics/Bitmap$Config;)Landroid/graphics/Bitmap;"), colors, source_width, source_height, argb);
    if (result && width > 0 && height > 0 && (width != source_width || height != source_height)) {
        double scale = std::min(double(width) / source_width, double(height) / source_height);
        width = std::max(1, int(source_width * scale));
        height = std::max(1, int(source_height * scale));
        jobject scaled = env->CallStaticObjectMethod(bitmap, env->GetStaticMethodID(bitmap, "createScaledBitmap", "(Landroid/graphics/Bitmap;IIZ)Landroid/graphics/Bitmap;"), result, width, height, JNI_TRUE);
        env->DeleteLocalRef(result);
        result = scaled;
    }
    if (colors) env->DeleteLocalRef(colors);
    env->DeleteLocalRef(argb);
    env->DeleteLocalRef(config);
    env->DeleteLocalRef(bitmap);
    return result;
}

static jobject unsupported_image(JNIEnv* env, jobject, ...) {
    unsupported(env, "MediaMetadataRetriever indexed images and frames");
    return nullptr;
}
static jbyteArray embedded(JNIEnv*, jobject, jint) { return nullptr; }
}

static bool install_retriever(JNIEnv* env) {
    jclass type = env->FindClass("android/media/MediaMetadataRetriever");
    if (!type) return false;
    retriever::context = env->GetFieldID(type, "mNativeContext", "J");
    if (!retriever::context) { env->DeleteLocalRef(type); return false; }
#define RETRIEVER_METHOD(name, signature, function) {const_cast<char*>(name), const_cast<char*>(signature), (void*)function}
    JNINativeMethod natives[] = {
        RETRIEVER_METHOD("native_init", "()V", no_init),
        RETRIEVER_METHOD("native_setup", "()V", retriever::setup),
        RETRIEVER_METHOD("release", "()V", retriever::release),
        RETRIEVER_METHOD("native_finalize", "()V", retriever::release),
        RETRIEVER_METHOD("setDataSource", "(Ljava/io/FileDescriptor;JJ)V", retriever::source_fd),
        RETRIEVER_METHOD("_setDataSource", "(Landroid/media/MediaDataSource;)V", retriever::source_callback),
        RETRIEVER_METHOD("_setDataSource", "(Landroid/os/IBinder;Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;)V", retriever::source_uri),
        RETRIEVER_METHOD("extractMetadata", "(I)Ljava/lang/String;", retriever::metadata),
        RETRIEVER_METHOD("_getFrameAtTime", "(JIII)Landroid/graphics/Bitmap;", retriever::frame),
        RETRIEVER_METHOD("getEmbeddedPicture", "(I)[B", retriever::embedded),
        RETRIEVER_METHOD("_getFrameAtIndex", "(IILandroid/media/MediaMetadataRetriever$BitmapParams;)Ljava/util/List;", retriever::unsupported_image),
        RETRIEVER_METHOD("_getImageAtIndex", "(ILandroid/media/MediaMetadataRetriever$BitmapParams;)Landroid/graphics/Bitmap;", retriever::unsupported_image),
        RETRIEVER_METHOD("getThumbnailImageAtIndex", "(ILandroid/media/MediaMetadataRetriever$BitmapParams;II)Landroid/graphics/Bitmap;", retriever::unsupported_image)
    };
#undef RETRIEVER_METHOD
    int result = env->RegisterNatives(type, natives, sizeof(natives) / sizeof(natives[0]));
    env->DeleteLocalRef(type);
    if (result < 0) return false;
    fprintf(stderr, "SDRETRIEVER=installed|backend=gstreamer|deadline_seconds=8\n");
    return true;
}
