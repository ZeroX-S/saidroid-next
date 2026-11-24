#!/usr/bin/env python3
"""Verify the Bionic LP64 heap ABI and accounting of mmap-backed allocations."""
from pathlib import Path
import shutil
import subprocess
import tempfile


repository = Path(__file__).resolve().parents[3]
jdk = Path(shutil.which("javac")).resolve().parents[1]
probe = r'''
#include <assert.h>
#include <malloc.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct mallinfo2 bionic_mallinfo(void);
int main(void) {
    _Static_assert(sizeof(struct mallinfo) == 10 * sizeof(int), "Host legacy ABI changed");
    _Static_assert(sizeof(struct mallinfo2) == 80, "Bionic LP64 ABI changed");
    struct mallinfo2 before = bionic_mallinfo();
    size_t length = 32 * 1024 * 1024;
    void *allocation = malloc(length);
    assert(allocation != NULL);
    memset(allocation, 0x5a, length);
    struct mallinfo2 allocated = bionic_mallinfo();
    assert(allocated.uordblks >= before.uordblks + length);
    assert(allocated.usmblks >= before.usmblks + length);
    assert(allocated.usmblks == allocated.uordblks + allocated.fordblks);
    assert(allocated.hblkhd >= length);
    assert(((volatile unsigned char *)allocation)[length - 1] == 0x5a);
    free(allocation);
    struct mallinfo2 released = bionic_mallinfo();
    assert(released.uordblks + length <= allocated.uordblks);
    printf("MALLINFO=PASS|return_bytes=%zu|total=%zu|allocated=%zu|free=%zu|mmap_bytes=%zu\n",
           sizeof(allocated), allocated.usmblks, allocated.uordblks,
           allocated.fordblks, allocated.hblkhd);
}
'''

with tempfile.TemporaryDirectory(prefix="saildroid-mallinfo-") as temporary:
    folder = Path(temporary)
    source = folder / "probe.c"
    source.write_text(probe)
    command = ["gcc", "-O2", "-Wall", "-Wextra", "-ffunction-sections", "-fdata-sections",
               "-I" + str(jdk / "include"), "-I" + str(jdk / "include/linux"),
               str(repository / "native/compat/api29-host.c"), str(source),
               "-Wl,--gc-sections", "-ldl", "-pthread", "-o", str(folder / "probe")]
    subprocess.run(command, check=True, timeout=60)
    subprocess.run([str(folder / "probe")], check=True, timeout=10)
