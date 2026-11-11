.method private blacklist touchTarget(FF)LSdWindowSession$Window;
    .registers 10

    invoke-direct {p0}, LSdWindowSession;->orderedWindows()Ljava/util/ArrayList;
    move-result-object v0
    invoke-virtual {v0}, Ljava/util/ArrayList;->size()I
    move-result v1
    add-int/lit8 v1, v1, -0x1

    :touch_window_loop
    if-ltz v1, :no_touch_window
    invoke-virtual {v0, v1}, Ljava/util/ArrayList;->get(I)Ljava/lang/Object;
    move-result-object v2
    check-cast v2, LSdWindowSession$Window;
    iget v3, v2, LSdWindowSession$Window;->visibility:I
    if-nez v3, :next_touch_window
    iget-object v3, v2, LSdWindowSession$Window;->sender:Landroid/view/InputEventSender;
    if-eqz v3, :next_touch_window
    iget-object v3, v2, LSdWindowSession$Window;->attributes:Landroid/view/WindowManager$LayoutParams;
    iget v3, v3, Landroid/view/WindowManager$LayoutParams;->flags:I
    and-int/lit8 v4, v3, 0x10
    if-nez v4, :next_touch_window
    iget-object v4, v2, LSdWindowSession$Window;->frame:Landroid/graphics/Rect;
    iget v5, v4, Landroid/graphics/Rect;->left:I
    int-to-float v5, v5
    cmpl-float v6, p1, v5
    if-ltz v6, :outside_touch_window
    iget v5, v4, Landroid/graphics/Rect;->right:I
    int-to-float v5, v5
    cmpg-float v6, p1, v5
    if-gez v6, :outside_touch_window
    iget v5, v4, Landroid/graphics/Rect;->top:I
    int-to-float v5, v5
    cmpl-float v6, p2, v5
    if-ltz v6, :outside_touch_window
    iget v5, v4, Landroid/graphics/Rect;->bottom:I
    int-to-float v5, v5
    cmpg-float v6, p2, v5
    if-ltz v6, :selected_touch_window

    :outside_touch_window
    and-int/lit8 v4, v3, 0x28
    if-nez v4, :next_touch_window

    :selected_touch_window
    and-int/lit8 v4, v3, 0x8
    if-eqz v4, :return_touch_window
    sget-object v4, Ljava/lang/System;->err:Ljava/io/PrintStream;
    const-string v5, "SDINPUT=nonfocusable_touch_target"
    invoke-virtual {v4, v5}, Ljava/io/PrintStream;->println(Ljava/lang/String;)V

    :return_touch_window
    return-object v2

    :next_touch_window
    add-int/lit8 v1, v1, -0x1
    goto :touch_window_loop

    :no_touch_window
    const/4 v0, 0x0
    return-object v0
.end method
