"""Prevent dependency loads from replacing the installed host media bindings."""


def patch(source):
    before = """\t\tfound = (soinfo *)handle;
\t\tsym = apkenv_lookup_in_library(&found, symbol);
"""
    after = """\t\tfound = (soinfo *)handle;
\t\tsym = apkenv_lookup_in_library(&found, symbol);
\t\t/* The host initializes media JNI explicitly before installing its media
\t\t * bindings. An application dependency load must not run that initializer
\t\t * again and replace those bindings. Other JNI delegation stays available. */
\t\tif (sym && found != (soinfo *)handle && !strcmp(symbol, "JNI_OnLoad") &&
\t\t    !strcmp(found->name, "libmedia_jni.so"))
\t\t\tsym = NULL;
"""
    assert source.count(before) == 1, "The verified handle lookup differs"
    return source.replace(before, after)
