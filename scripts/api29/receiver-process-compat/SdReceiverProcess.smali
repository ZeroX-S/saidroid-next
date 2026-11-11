.class public final LSdReceiverProcess;
.super Ljava/lang/Object;
.source "SdReceiverProcess.java"

.method private constructor blacklist <init>()V
    .registers 1
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static blacklist start(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V
    .registers 7
    sget-object v0, LSdApkPackage;->NAME:Ljava/lang/String;
    invoke-virtual {v0, p0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0
    if-eqz v0, :wrong_package
    new-instance v0, Landroid/content/ComponentName;
    invoke-direct {v0, p0, p1}, Landroid/content/ComponentName;-><init>(Ljava/lang/String;Ljava/lang/String;)V
    const/4 v1, 0x0
    invoke-static {v0, v1}, LSdApkPackage;->receiverInfo(Landroid/content/ComponentName;I)Landroid/content/pm/ActivityInfo;
    move-result-object v0
    if-eqz v0, :wrong_receiver
    iget-object v1, v0, Landroid/content/pm/ActivityInfo;->applicationInfo:Landroid/content/pm/ApplicationInfo;
    iget-boolean v1, v1, Landroid/content/pm/ApplicationInfo;->enabled:Z
    if-eqz v1, :wrong_receiver
    iget-object v0, v0, Landroid/content/pm/ActivityInfo;->processName:Ljava/lang/String;
    invoke-virtual {p2, v0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0
    if-eqz v0, :wrong_receiver
    invoke-static {}, LSdApkPackage;->parsed()Landroid/content/pm/PackageParser$Package;
    move-result-object v0
    iget-object v0, v0, Landroid/content/pm/PackageParser$Package;->providers:Ljava/util/ArrayList;
    invoke-virtual {v0}, Ljava/util/ArrayList;->iterator()Ljava/util/Iterator;
    move-result-object v0
    :next_provider
    invoke-interface {v0}, Ljava/util/Iterator;->hasNext()Z
    move-result v1
    if-eqz v1, :no_provider
    invoke-interface {v0}, Ljava/util/Iterator;->next()Ljava/lang/Object;
    move-result-object v1
    check-cast v1, Landroid/content/pm/PackageParser$Provider;
    iget-object v1, v1, Landroid/content/pm/PackageParser$Provider;->info:Landroid/content/pm/ProviderInfo;
    iget-boolean v2, v1, Landroid/content/pm/ProviderInfo;->enabled:Z
    if-eqz v2, :next_provider
    iget-object v2, v1, Landroid/content/pm/ProviderInfo;->applicationInfo:Landroid/content/pm/ApplicationInfo;
    iget-boolean v2, v2, Landroid/content/pm/ApplicationInfo;->enabled:Z
    if-eqz v2, :next_provider
    iget-object v2, v1, Landroid/content/pm/ProviderInfo;->name:Ljava/lang/String;
    if-eqz v2, :next_provider
    iget-object v2, v1, Landroid/content/pm/ProviderInfo;->packageName:Ljava/lang/String;
    invoke-virtual {p0, v2}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v2
    if-eqz v2, :next_provider
    invoke-static {v1}, LSdApkPackage;->providerProcess(Landroid/content/pm/ProviderInfo;)Ljava/lang/String;
    move-result-object v2
    invoke-virtual {p2, v2}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v2
    if-eqz v2, :next_provider
    iget-object v2, v1, Landroid/content/pm/ProviderInfo;->name:Ljava/lang/String;
    invoke-static {p0, v2, p2}, Lorg/saildroid/host/HostApi;->startProviderProcess(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V
    new-instance v0, Ljava/lang/StringBuilder;
    const-string v3, "SDBROADCAST=receiver_process_bootstrap|provider="
    invoke-direct {v0, v3}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V
    invoke-virtual {v0, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    const-string v1, "|process="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v0
    sget-object v1, Ljava/lang/System;->err:Ljava/io/PrintStream;
    invoke-virtual {v1, v0}, Ljava/io/PrintStream;->println(Ljava/lang/String;)V
    return-void
    :no_provider
    new-instance v0, Ljava/lang/UnsupportedOperationException;
    const-string v1, "Receiver process has no enabled declared provider bootstrap"
    invoke-direct {v0, v1}, Ljava/lang/UnsupportedOperationException;-><init>(Ljava/lang/String;)V
    throw v0
    :wrong_package
    new-instance v0, Ljava/lang/SecurityException;
    const-string v1, "Receiver package differs from the hosted APK"
    invoke-direct {v0, v1}, Ljava/lang/SecurityException;-><init>(Ljava/lang/String;)V
    throw v0
    :wrong_receiver
    new-instance v0, Ljava/lang/SecurityException;
    const-string v1, "Receiver process differs from its enabled declaration"
    invoke-direct {v0, v1}, Ljava/lang/SecurityException;-><init>(Ljava/lang/String;)V
    throw v0
.end method

.method public static blacklist dispatch(Landroid/os/Parcel;Landroid/os/Parcel;)Z
    .registers 9
    invoke-static {}, Landroid/os/Binder;->getCallingUid()I
    move-result v0
    invoke-static {}, Landroid/os/Process;->myUid()I
    move-result v1
    if-ne v0, v1, :wrong_uid
    invoke-virtual {p0}, Landroid/os/Parcel;->readString()Ljava/lang/String;
    move-result-object v0
    sget-object v1, LSdApkPackage;->NAME:Ljava/lang/String;
    invoke-virtual {v1, v0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0
    if-eqz v0, :wrong_package
    sget-object v0, Landroid/content/Intent;->CREATOR:Landroid/os/Parcelable$Creator;
    invoke-interface {v0, p0}, Landroid/os/Parcelable$Creator;->createFromParcel(Landroid/os/Parcel;)Ljava/lang/Object;
    move-result-object v0
    check-cast v0, Landroid/content/Intent;
    invoke-virtual {p0}, Landroid/os/Parcel;->readInt()I
    move-result v1
    invoke-virtual {p0}, Landroid/os/Parcel;->readString()Ljava/lang/String;
    move-result-object v2
    invoke-virtual {p0}, Landroid/os/Parcel;->readBundle()Landroid/os/Bundle;
    move-result-object v3
    invoke-virtual {p0}, Landroid/os/Parcel;->createStringArray()[Ljava/lang/String;
    move-result-object v4
    invoke-virtual {p0}, Landroid/os/Parcel;->readInt()I
    move-result v5
    :try_start
    invoke-static/range {v0 .. v5}, LSdManifestReceivers;->deliverLocal(Landroid/content/Intent;ILjava/lang/String;Landroid/os/Bundle;[Ljava/lang/String;I)V
    :try_end
    .catch Ljava/lang/RuntimeException; {:try_start .. :try_end} :runtime_failure
    .catch Ljava/lang/Exception; {:try_start .. :try_end} :checked_failure
    invoke-virtual {p1}, Landroid/os/Parcel;->writeNoException()V
    const/4 v0, 0x1
    return v0
    :runtime_failure
    move-exception v0
    throw v0
    :checked_failure
    move-exception v0
    new-instance v1, Ljava/lang/IllegalStateException;
    const-string v2, "Manifest receiver dispatch failed"
    invoke-direct {v1, v2, v0}, Ljava/lang/IllegalStateException;-><init>(Ljava/lang/String;Ljava/lang/Throwable;)V
    throw v1
    :wrong_uid
    new-instance v0, Ljava/lang/SecurityException;
    const-string v1, "Receiver caller UID differs"
    invoke-direct {v0, v1}, Ljava/lang/SecurityException;-><init>(Ljava/lang/String;)V
    throw v0
    :wrong_package
    new-instance v0, Ljava/lang/SecurityException;
    const-string v1, "Receiver caller package differs"
    invoke-direct {v0, v1}, Ljava/lang/SecurityException;-><init>(Ljava/lang/String;)V
    throw v0
.end method
