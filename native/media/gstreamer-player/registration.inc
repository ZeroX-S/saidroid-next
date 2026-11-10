static jobject unsupported_10(JNIEnv*e,jobject,...){unsupported(e,"native_getMetrics()Landroid/os/PersistableBundle;");return nullptr;}
static void unsupported_11(JNIEnv*e,jobject,...){unsupported(e,"setPlaybackParams(Landroid/media/PlaybackParams;)V");}
static jobject unsupported_12(JNIEnv*e,jobject,...){unsupported(e,"getPlaybackParams()Landroid/media/PlaybackParams;");return nullptr;}
static void unsupported_13(JNIEnv*e,jobject,...){unsupported(e,"setSyncParams(Landroid/media/SyncParams;)V");}
static jobject unsupported_14(JNIEnv*e,jobject,...){unsupported(e,"getSyncParams()Landroid/media/SyncParams;");return nullptr;}
static jint unsupported_39(JNIEnv*e,jobject,...){unsupported(e,"native_pullBatteryData(Landroid/os/Parcel;)I");return 0;}
static jint unsupported_40(JNIEnv*e,jobject,...){unsupported(e,"native_setRetransmitEndpoint(Ljava/lang/String;I)I");return 0;}
static jint unsupported_42(JNIEnv*e,jobject,...){unsupported(e,"native_applyVolumeShaper(Landroid/media/VolumeShaper$Configuration;Landroid/media/VolumeShaper$Operation;)I");return 0;}
static jobject unsupported_43(JNIEnv*e,jobject,...){unsupported(e,"native_getVolumeShaperState(I)Landroid/media/VolumeShaper$State;");return nullptr;}
static void unsupported_44(JNIEnv*e,jobject,...){unsupported(e,"_prepareDrm([B[B)V");}
static void unsupported_45(JNIEnv*e,jobject,...){unsupported(e,"_releaseDrm()V");}
static jboolean unsupported_46(JNIEnv*e,jobject,...){unsupported(e,"native_setOutputDevice(I)Z");return 0;}
static jint unsupported_47(JNIEnv*e,jobject,...){unsupported(e,"native_getRoutedDeviceId()I");return 0;}
static void unsupported_48(JNIEnv*e,jobject,...){unsupported(e,"native_enableDeviceCallback(Z)V");}
static jobject get_buffering_params(JNIEnv*e,jobject){unsupported(e,"getBufferingParams()Landroid/media/BufferingParams;");return nullptr;}
static void set_buffering_params(JNIEnv*e,jobject,jobject){unsupported(e,"setBufferingParams(Landroid/media/BufferingParams;)V");}
static JNINativeMethod methods[]={
 {const_cast<char*>("nativeSetDataSource"),const_cast<char*>("(Landroid/os/IBinder;Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;)V"),(void*)source_uri},
 {const_cast<char*>("_setDataSource"),const_cast<char*>("(Ljava/io/FileDescriptor;JJ)V"),(void*)source_fd},
 {const_cast<char*>("_setDataSource"),const_cast<char*>("(Landroid/media/MediaDataSource;)V"),(void*)source_callback},
 {const_cast<char*>("_setVideoSurface"),const_cast<char*>("(Landroid/view/Surface;)V"),(void*)set_surface},
 {const_cast<char*>("_prepare"),const_cast<char*>("()V"),(void*)prepare_sync},
 {const_cast<char*>("prepareAsync"),const_cast<char*>("()V"),(void*)prepare_async},
 {const_cast<char*>("_start"),const_cast<char*>("()V"),(void*)start},
 {const_cast<char*>("_stop"),const_cast<char*>("()V"),(void*)stop},
 {const_cast<char*>("getVideoWidth"),const_cast<char*>("()I"),(void*)width},
 {const_cast<char*>("getVideoHeight"),const_cast<char*>("()I"),(void*)height},
 {const_cast<char*>("native_getMetrics"),const_cast<char*>("()Landroid/os/PersistableBundle;"),(void*)unsupported_10},
 {const_cast<char*>("setPlaybackParams"),const_cast<char*>("(Landroid/media/PlaybackParams;)V"),(void*)unsupported_11},
 {const_cast<char*>("getPlaybackParams"),const_cast<char*>("()Landroid/media/PlaybackParams;"),(void*)unsupported_12},
 {const_cast<char*>("setSyncParams"),const_cast<char*>("(Landroid/media/SyncParams;)V"),(void*)unsupported_13},
 {const_cast<char*>("getSyncParams"),const_cast<char*>("()Landroid/media/SyncParams;"),(void*)unsupported_14},
 {const_cast<char*>("_seekTo"),const_cast<char*>("(JI)V"),(void*)seek},
 {const_cast<char*>("_notifyAt"),const_cast<char*>("(J)V"),(void*)notify},
 {const_cast<char*>("_pause"),const_cast<char*>("()V"),(void*)pause_player},
 {const_cast<char*>("isPlaying"),const_cast<char*>("()Z"),(void*)isplaying},
 {const_cast<char*>("getCurrentPosition"),const_cast<char*>("()I"),(void*)position},
 {const_cast<char*>("getDuration"),const_cast<char*>("()I"),(void*)duration},
 {const_cast<char*>("getBufferingParams"),const_cast<char*>("()Landroid/media/BufferingParams;"),(void*)get_buffering_params},
 {const_cast<char*>("setBufferingParams"),const_cast<char*>("(Landroid/media/BufferingParams;)V"),(void*)set_buffering_params},
 {const_cast<char*>("_release"),const_cast<char*>("()V"),(void*)release},
 {const_cast<char*>("_reset"),const_cast<char*>("()V"),(void*)reset},
 {const_cast<char*>("_setAudioStreamType"),const_cast<char*>("(I)V"),(void*)stream},
 {const_cast<char*>("_getAudioStreamType"),const_cast<char*>("()I"),(void*)getstream},
 {const_cast<char*>("setParameter"),const_cast<char*>("(ILandroid/os/Parcel;)Z"),(void*)parameter},
 {const_cast<char*>("setLooping"),const_cast<char*>("(Z)V"),(void*)looping},
 {const_cast<char*>("isLooping"),const_cast<char*>("()Z"),(void*)islooping},
 {const_cast<char*>("_setVolume"),const_cast<char*>("(FF)V"),(void*)volume},
 {const_cast<char*>("native_invoke"),const_cast<char*>("(Landroid/os/Parcel;Landroid/os/Parcel;)I"),(void*)invoke},
 {const_cast<char*>("native_setMetadataFilter"),const_cast<char*>("(Landroid/os/Parcel;)I"),(void*)filter},
 {const_cast<char*>("native_getMetadata"),const_cast<char*>("(ZZLandroid/os/Parcel;)Z"),(void*)metadata},
 {const_cast<char*>("native_init"),const_cast<char*>("()V"),(void*)no_init},
 {const_cast<char*>("native_setup"),const_cast<char*>("(Ljava/lang/Object;)V"),(void*)setup},
 {const_cast<char*>("native_finalize"),const_cast<char*>("()V"),(void*)release},
 {const_cast<char*>("getAudioSessionId"),const_cast<char*>("()I"),(void*)getsession},
 {const_cast<char*>("setAudioSessionId"),const_cast<char*>("(I)V"),(void*)session},
 {const_cast<char*>("_setAuxEffectSendLevel"),const_cast<char*>("(F)V"),(void*)aux_level},
 {const_cast<char*>("attachAuxEffect"),const_cast<char*>("(I)V"),(void*)aux},
 {const_cast<char*>("native_pullBatteryData"),const_cast<char*>("(Landroid/os/Parcel;)I"),(void*)unsupported_39},
 {const_cast<char*>("native_setRetransmitEndpoint"),const_cast<char*>("(Ljava/lang/String;I)I"),(void*)unsupported_40},
 {const_cast<char*>("setNextMediaPlayer"),const_cast<char*>("(Landroid/media/MediaPlayer;)V"),(void*)next_player},
 {const_cast<char*>("native_applyVolumeShaper"),const_cast<char*>("(Landroid/media/VolumeShaper$Configuration;Landroid/media/VolumeShaper$Operation;)I"),(void*)unsupported_42},
 {const_cast<char*>("native_getVolumeShaperState"),const_cast<char*>("(I)Landroid/media/VolumeShaper$State;"),(void*)unsupported_43},
 {const_cast<char*>("_prepareDrm"),const_cast<char*>("([B[B)V"),(void*)unsupported_44},
 {const_cast<char*>("_releaseDrm"),const_cast<char*>("()V"),(void*)unsupported_45},
 {const_cast<char*>("native_setOutputDevice"),const_cast<char*>("(I)Z"),(void*)unsupported_46},
 {const_cast<char*>("native_getRoutedDeviceId"),const_cast<char*>("()I"),(void*)unsupported_47},
 {const_cast<char*>("native_enableDeviceCallback"),const_cast<char*>("(Z)V"),(void*)unsupported_48},
};
