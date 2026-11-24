# Native display events on API28

`native-display-events.c` routes the API28 `DisplayEventReceiver` instance ABI
through the window host. Mapped application processes receive events from
Wayland frame acknowledgements and the existing startup frame clock. Headless
service processes use an on-demand monotonic timer. Android's original
`DisplayEventDispatcher` and NDK `Choreographer` own their Looper callbacks and
delayed callback queues.

The adapter matches the shipped API28 libgui constructor, destructor, instance
methods, 16-byte receiver storage, and 24-byte event layout. Receiver state and
file descriptors are host-owned. Destruction removes the state under the same
lock used by event delivery and closes its descriptors. Repeated one-shot
requests coalesce. Rate zero disables the periodic subscription.

## Building the verified release library

The builder requires the extracted r323g payload and the retained cross-build
inputs referenced by its window build record. Use a fresh output directory.

```sh
python3 native/window/build-native-display-vm.py \
  --baseline-root /tmp/saildroid-webview-runtime-r323g-20261109/root \
  --output /tmp/saildroid-native-display-build
```

It reproduces the baseline library byte-for-byte before compiling the adapter.
The resulting `build-result.json` records compiler commands, input hashes,
dynamic dependencies, and preserved and added exports. The product builder and
native transition recipe include the adapter source and header.

## Regression checks

```sh
gcc -std=c11 -O2 -Wall -Wextra -Werror -pthread \
  native/window/tests/native-display-events.c -o /tmp/native-display-test
/tmp/native-display-test
```

`tests/NativeDisplayActivity.java` and `tests/choreographer-probe.c` form a normal
APK fixture. The fixture checks receiver initialization and disposal, then
creates two independent original NDK Choreographers. Each dispatches three
callbacks on its owning Looper, including a 40 ms delayed callback. The result
records callback counts, thread and timestamp errors, and initialization and
delay measurements.

## 2026-11-10 WeChat service-account black-screen investigation

The service-account and public-account page still opens to a black screen.
The captured runs used
`saildroid-runtime-api28-r323h-dev-20261109-0.321.59-66.aarch64` and source
commit `f66de6905c403bb19fa48655efa188e64593f101`. The remaining investigation
covers initialization after device-information completion and WeChat's
customized parallel rendering pipeline. A runtime repair and visual acceptance
remain pending.

### Device observations

- The device-information reply is a 740-byte StandardMethodCodec success
  envelope. Its first byte is `0` and its value type is `13`, a map.
- GDB matched the response's persistent Dart handle to the reply closure. The
  closure executed with one argument and returned normally.
- A later trace read raw Dart metadata and observed the reply closure followed
  by two zero-argument microtasks. All three returned class `171`, the observed
  null result, with `returned_error=false`. The checked Dart error classes are
  `40` through `44` in this library.
- The subsequent BufferQueue inspection reported `allocated_slots=0` and
  `queue_size=0`, with an active EGL producer connection and `abandoned=0`.

GDB directly observed execution at sites for which internal perf probes
recorded zero events. Probe absence is insufficient to diagnose an unexecuted
reply. The diagnostic null result from
`DartMicrotaskQueue::GetForCurrentThread` also requires further context before
it can support a queue-blocking diagnosis.

### Trace handling

An early-startup GDB trace that invoked Dart metadata APIs timed out. SIGINT
and SIGTERM failed to finish the debugger. After checking the debugger's PID,
start time, and owned command, cleanup used SIGKILL. The attached WeChat
process subsequently exited. Its failure metadata was retained and WeChat was
restored through the normal desktop entry.

The later trace read metadata directly from inferior memory. Its bounded
observation ended with SIGINT and a clean detach. The final captured state
recorded `TracerPid=0`, a sleeping WeChat process, and removal of all four owned
tracing workspaces. ART startup tracing used
`handle SIGSEGV nostop noprint pass` to preserve managed-runtime signal handling.

### Retained evidence

The workspace retains the full captures under
`artifacts/wechat-service-black-20261109`. This record contains observed results
and SHA-256 references for those captures.

| Evidence file | SHA-256 |
| --- | --- |
| `response-gdb-23.json` | `0e05b7e9cd4cd3cf3a774a5f02d00248a3d151861fccf8b8f86658b1613774d0` |
| `response-readonly-26.json` | `f1d39a3b8105eefa494eedb1a3a5e7fc42e9591b98058af6cf3a709d64dde7d9` |
| `bufferqueue-after-request.json` | `32909c4626c2923d22ab96523c5793f71e530c27c9d0bf80e113883596491ace` |
| `gdb-timeout-cleanup-final-24.json` | `e83952a0d27034fdb580b7d38a09616e0be4ddc9b3059980650267d1814cd670` |
| `gdb-failure-state-24.json` | `bac1aabbfbea3d321c9400393382c7a0cb058da39fea5c4cd55f9735bbd2c20c` |
| `restore-normal-entry-25.json` | `c9ad5e824481eea7e53884ef9ce7ad2a9f6d76858513ca0ef0e76e591d1ad0d8` |
| `verified-state-20261110.json` | `7669286182b522292ab670eea6e3dc3cef1bce1dbba045247883855f2e20d3e0` |
