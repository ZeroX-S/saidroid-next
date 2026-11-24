# Software Keymaster foundation (VM only)

`tests/soft-keymaster-contract.c` exercises the unchanged original Android 10
`libsoftkeymasterdevice.so` and its genuine native dependency closure through
the current private Bionic loader and cross-DSO CFI checks, as UID 65534.
This is an internal foundation contract, not an AndroidKeyStore implementation,
keystore daemon, hardware claim, original CTS run, or phone deployment.

The original exported `soft_keymaster2_device_module` has null module methods,
so it is not a factory. The probe compiles `sizeof` and `alignof` from the
unchanged official API29 SoftKeymasterDevice, libc++, BoringSSL and public HAL
headers, then uses the actual native allocation backend and original exported
constructor/get-device functions. The computed 904-byte size independently
matches the original keystore binary's allocation before the same constructor.
Original `common.close` destroys the object. Header references are not a claim
that the original binary was rebuilt from those sources.

The compiler-only ABI query renames libc++'s old internal `__is_convertible`
trait to avoid a GCC 13 builtin-name collision; no source header, class field,
layout or native implementation changes. Optimization removes unused header
ASN.1 tables so the query has no crypto linkage. The original private loader
currently rejects weak symbols via dlsym, including C++ operator new; the probe
uses the exact already-loaded `libc_bio.so.0` allocation backend instead. No
loader change or global runtime-handle replacement is involved.

`softkeymaster194-v6-contract.json` records 53 successful assertions: software
only flags, no hardware-enforced key authorizations, rejection before explicit
configuration, fresh RSA-2048 and EC P-256 keys, native streaming sign/verify,
wrong-key/message/signature/key-blob rejection, public-key export, and invalid
operation rejection after abort. Configuration is explicit ephemeral Android
10 version 100000 with patch level 0, with no security patch attestation claim.
No attestation/TEE/StrongBox test is performed. All generated keys stay in
memory, returned buffers are cleared/freed, the device closes, and the private
run directory is removed. No account credentials or existing key data are used.

Earlier failed build and runtime attempts are retained. The signing crash was
traced with the actual PC and original source to passing a null parameter set
to finish; the caller now supplies a valid empty set. This is a harness API-call
correction, not an original-library or assertion modification.

The missing next layers remain real per-UID durable alias storage, Binder
keystore service, original AndroidKeyStore provider integration, key-use
permission policy, and phone/original-module regression. Software operations
alone do not satisfy those interfaces.

## Per-UID durable blob store and native Binder prototype (VM only)

`private-blob-store.hpp` is a storage primitive using a pinned installer-provided
service directory, exact service ownership/modes, separately opened directory
FDs, thread and process locks, alias-to-hex filenames, and per-UID namespaces.
It refuses symlinks, hardlinks, devices/FIFOs/directories, wrong owners/modes,
oversized or malformed files. Creates use fsync and renameat2 NOREPLACE; deletion
checks the pinned inode and synchronizes the directory. Blob read buffers and
returned key data have volatile wipe guards. This is software storage protected
by Linux access controls, not encrypted-at-rest or hardware-backed storage.

`private-key-store194-v3-contract.json` proves 19 actual kernel Binder requests
with 106 parent assertions. Actual client UIDs 10000 and 10001 derive from the
existing genuinely verified signed-APK registry; request sender fields and
claimed UID 0 are ignored in favor of the kernel's sender_euid. The root test
orchestrator preloads immutable identity metadata and forks the service as
actual UID10050; it does not install an account, unit, or system-wide node.

Real RSA and EC keys are generated, stored, and used by their own UIDs. A second
UID cannot read the service directory, sign/delete another UID's alias, or use
a same-name key to validate the first UID's signature. Unknown actual UID19999
is denied. The complete native service/backend stops and restarts; both keys
remain usable from durable blobs. Owner deletion preserves the second UID's
key. Both aliases are then removed, all service/client processes finish, and
the private binderfs nodes/mount/state directories are cleaned. The prototype
uses an explicitly internal protocol, not Android IKeystoreService or Java
AndroidKeyStore. APK fixtures supply verified identities only; their Service
classes are not executed.

The first prototype run completed all 19 operations but its cleanup loop tried
to unlink binderfs/features. That entire result remains failed. Subsequent
runs unlink only the two test-owned nodes and explicitly unmount; v3 is the
current result for the single-allocation/wiped read buffer implementation.

`private-blob-files194-v2-contract.json` adds 25 actual-UID filesystem cases
with synthetic non-secret data, including threaded and multi-process create
contention (one winner, seven duplicate rejections), path-like literal aliases,
unknown UIDs, permissions, links, invalid sizes/formats and deletion boundaries.
Outside sentinels stay unchanged and no pending transaction files remain. This
separate filesystem contract does not claim cryptography; native crypto and
real Binder behavior are established by the earlier independent contracts.

## Standard IKeystoreService interface prototype (VM only)

The new `java/SoftwareKeystoreService.java` extends the unchanged original API29
IKeystoreService.Stub. `software-keystore-jni.cpp` decodes the original tagged
KeymasterArguments into real native parameters and returns genuine native
characteristics, public exports and streaming operation results. Incoming caller
UID comes from matching Android Binder JNI in an actual transaction; explicit
other-UID and root requests are denied. Java Binder operation tokens and native
handles are UID-owned. Private key material never returns across this interface.

This intentionally supports only a bounded RSA/EC, no-auth software subset.
Generation tags outside its supported set, auth-bound keys, flags/StrongBox,
imports, blob/certificate storage, attestation and other missing methods return
explicit unsupported errors. No authentication or hardware service is fabricated.
The supervisor supplies a pinned state FD and the verified fixture UID subset;
production installer, service discovery/lifecycle, caller-death cleanup and the
original AndroidKeyStore provider integration remain unfinished.

`standard-keystore194-v2-contract.json` proves original proxy/stub and original
async callback classes over actual Java/Parcel/JNI/kernel Binder: 554 client
assertions and 122 real callbacks for actual UID10000/10001, plus unknown actual
UID19999 denials. Both UIDs generate separate same-name RSA/EC keys, receive
actual software-only characteristics and public X509 exports, sign/verify, reject
modified messages and stale finished tokens, and reject duplicate replacement.
A complete service/native backend restart reloads the same keys (identical public
DER hashes), then both owners delete their keys. Independent host OpenSSL
verifies all eight exported-public-key signatures. All processes, binderfs mount
and generated private key state are removed. No phone or original CTS is run.

The first runtime attempt exposed a real serialization mismatch on error results:
OperationResult(int) leaves outParams null, while the original writeToParcel
requires it. Error callbacks now carry an actual empty KeymasterArguments. The
failed attempt and its cleanup evidence remain preserved; v2 is the passed run.

`standard-keystore194-v5-contract.json` additionally proves 38 assertions across
two actual-UID Application contexts bound through original ActivityThread and
LoadedApk from the unchanged genuinely signed fixture APKs. The original
AndroidKeyStoreProvider and AndroidKeyStoreBCWorkaround load the native-backed
keys and sign RSA/ECDSA via the remote standard interface; getEncoded() on the
private objects is null. Independent OpenSSL verifies those four signatures,
and their public keys exactly match the earlier native exports. The complete
standard protocol/restart suite also passes on this same build. Actual entropy
requests now reach the original add_rng_entropy implementation. Empty original
KeymasterBlob wrappers are accepted as empty; non-empty unsupported application
bindings remain explicitly rejected. Original provider sources/classes were not
edited. No APK Activity/Service class is executed by this VM bootstrap.

The existing process-local service-discovery shim is explicitly seeded with the
actual remote Binder for this contract; no global servicemanager is claimed.
Certificate/blob storage and the original JCA key-pair generation entry remain
unfinished. Earlier javacrypto-path and empty-wrapper failures are retained.
The exact passed sources are snapshotted under the evidence keystore-snapshots
folder before further development.

`standard-keystore194-v6-contract.json` extends the same genuine provider path
through original JCA KeyPairGenerator and KeyStore SPI. Each UID creates RSA and
EC keys with actual self-signed certificates, checks public-key equality, loads
private objects and certificate chains, enumerates aliases, signs, and deletes
both key/certificate entries. All four certificate signatures verify, and
independent OpenSSL verifies the four additional public signatures and matches
the certificate public keys. This run includes 586 standard-interface client
assertions and 74 provider assertions, with all earlier native restart/cleanup
checks retained. No original CTS is represented by these internal assertions.

Trusted store configuration can now explicitly opt into record kind4 for values;
default key stores retain kinds1/3. Only kind4 values may atomically replace
same-kind records. A value cannot replace or read native private-key blobs.
Empty values, literal prefix listing and original certificate storage are real;
encrypted-at-rest flags and nonimplemented auth/hardware/import methods still
reject. The final state contains no generated key/value files after cleanup.

The original 25 filesystem boundaries pass again on this extended store
(`private-blob-files194-v3-contract.json`). A further 23 actual-UID typed-value
cases pass (`private-typed-values194-v1-contract.json`), using synthetic
non-secret bytes only. They cover empty values, per-UID same aliases, same-kind
atomic replacement, native key preservation, 8 threaded and 8 process writers,
default-kind restrictions, and refusal of links/permissions/malformed files in
listing or replacement. Outside sentinels stay unchanged, and fixture/pending
files are removed. Passed source snapshots are retained before further work.

## Original Google APK diagnostic (VM only)

The unchanged CtsKeystoreTestCases.apk (SHA256 1f67fa64...3d23055f) is freshly
signature-verified by actual PackageParser as UID65534, allocated real UID10000
in a fresh durable registry, and bound through ActivityThread with its declared
AndroidJUnitRunner. Its original KeyPairGeneratorTest class runs all 33 methods;
the original 3000000ms method timeout and hidden-api-checks=false are retained.
Eight actual mapped original Bionic dependency hashes are checked. Three
separate same-name glibc ART support libraries are explicitly distinguished by
real paths, ELF dependencies and hashes; basename alone was an invalid check.

`original-keystore194-v3.json` completes 29 passes/4 failures. Passing the real
KM_TAG_BLOCK_MODE unchanged to native Keymaster fixes two genuine failures.
`original-keystore194-v4.json` completes 31 passes/2 failures. The exact 33 IDs,
APK/config/signature/UID/native maps and driver DEX are identical; the only
service source change is that one authorization tag. Paired evidence is
`original-keystore194-keypair-paired-boundary.json`; raw failures are retained.
Both remaining original tests request unlocked-device-required=true, and are
still rejected because a trustworthy lock-state backend is absent. No flag,
assertion, identity or capability is spoofed to make those pass.

This is one complete original class in an explicitly private VM diagnostic, not
the complete Keystore module, phone result or formal Tradefed. The original APK,
private identity/key state, binderfs mount and all child processes are cleaned.
Initial setup failures (download after network isolation and mixed-name map
comparison) are preserved. Exact accepted source snapshots accompany evidence.

## Symmetric operations and native import (VM only)

The standard service prototype now accepts original native AES and HMAC key
creation, RAW symmetric import and PKCS8 RSA/EC import. All key operations still
use the unchanged original software Keymaster and eight mapped Bionic libraries.
The native result must contain the requested algorithm; only public asymmetric
X509 data may be exported. Generic value access cannot read or replace a native
key. Auth, lock-state, StrongBox and encrypted-at-rest flags remain unsupported.

`standard-keystore194-v8-completed-audit.json` verifies the actual completed
internal run on build15: 1,287 standard-client assertions, 338 additional raw
symmetric assertions and 60 additional original JCA symmetric/import assertions,
with 356 original callbacks. Real AES-GCM encrypt/decrypt and tamper rejection,
HMAC sign/verify, independent AndroidOpenSSL cross-checks, generated/imported
origin, malformed/wrong-format rejection, two actual client UIDs and complete
service/backend restart are covered. Original JCA SecretKey objects have null
encoding; original SPI secret-key generation/import/delete and native PKCS8
public-key/signature equality are checked. All generated state is removed.
The v8 wrapper itself falsely reports failure because its child summary omits
new markers. The separate auditor requires actual child exit0, all retained
client logs and cleanup; it preserves the original wrapper result unchanged.
The prior v7 run actually failed due an internal fixture passing MAC_LENGTH to
HMAC verify; the original HAL prohibits that parameter. Only the fixture call
was corrected, with no product native or assertion weakening.

`original-keystore194-keygenerator-paired-v1.json` records the full original
Google KeyGeneratorTest class before/after: 14/20 to 20/20, same exact 20 IDs,
APK/config/signature/allocated UID/native closure, no added exclusion. This is
an original-class VM diagnostic, not a full module or phone CTS result.
`MacTest` on build15 improves from 1/13 to 9/13 and exposes missing service-level
purpose/date enforcement and operation cleanup. Raw failures remain available.
The original 25 filesystem boundaries and 23 typed-value boundaries pass again
on the extended known record-kind set (v4/v2 evidence respectively).

## Service key-use policy and operation lifecycle (VM only)

Build17 adds service-side no-auth purpose/date/nonce policy from the original
API29 enforcement rules. Each begin obtains genuine native characteristics;
private operations must have an authorized purpose and valid active/expiry
window, using the actual service's kernel realtime clock. Original asymmetric
public encrypt/verify behavior is retained. Supplied origination nonces require
the key's genuine CALLER_NONCE authorization. Unsupported lock/auth tags remain
rejected at generation/import; this does not invent a lock or auth backend.
The policy runs before resource-pressure handling, so an invalid request cannot
cause pruning merely by reaching the wrapper quota.

The Java service tracks real Binder application tokens, original caller UIDs
and access-order operations. Ordinary app requests cannot create non-pruneable
operations. On genuine native capacity errors it aborts the least-recently-used
pruneable handle through a trusted service-only native lifecycle entry; it never
accepts an app-supplied owner for that entry. Real Binder death aborts every
remaining owned operation and removes tracking. Finished/aborted/error paths
remove tracking and unlink unused death recipients.

`standard-keystore194-v9-contract.json` passes the combined actual two-UID
RSA/EC/AES/HMAC/provider/restart suite plus direct purpose/date/nonce denials.
The lifecycle fixture starts 64 genuine operations, observes 48 native aborts,
verifies an old token is invalid while the newest token works, then exits
without explicit aborts. The real kernel Binder death callback reaps the
remaining 16 handles with zero native errors; a fresh process can immediately
use native capacity. All test-owned processes/state/mounts are removed.
`original-keystore194-mac-paired-v1.json` proves all 13 original MacTest methods
now pass, versus9/13 on build15 (and1/13 before symmetric/import support).
These are still VM-only original-class diagnostics, not phone/full-module CTS.

## Trusted lock-state transport foundation (VM only)

`mce-lock-state.hpp` queries a launcher-selected, canonical root-owned Unix
system-bus endpoint directly. It ignores app-selected bus environment values,
checks the actual socket peer UID, authenticates normally, resolves MCE to a
unique bus name and requires that service connection's actual Unix UID0. It
queries that exact connection and confirms MCE still owns the well-known name
before accepting an unlocked reply. Unknown state, unsupported Android user,
missing service, identity change and bounded connection/query failures remain
locked. It does not unlock the device or implement authentication/encrypted
storage. Production account and phone service integration remain separate work.

`mce-lock-state194-v6-contract.json` passes16 real private-D-Bus transport and
credential cases with explicitly simulated MCE events. An actual non-root name
owner and a non-root socket peer are rejected independently. Method and auth
stall cases terminate in about1s and2s. Query-time service name loss first
exposed a real stale-owner acceptance in v5; the before/after raw records and
old source snapshot are retained. All fixture processes and sockets are removed.
The query process uses an ordinary known NSS UID65534; an earlier attempt with
fixture-only UID10050 correctly failed normal D-Bus authentication without a
matching account. No host account was added or system bus changed.

`softkeymaster194-lock-tags-v1-contract.json` additionally checks73 actual native
assertions. Both RSA and EC retain UNLOCKED_DEVICE_REQUIRED and service-supplied
USER_ID through generation and subsequent genuine native characteristics;
ordinary native signing still succeeds without any lock backend. This proves
tag retention, not lock enforcement. Service-side enforcement is being built in
an offside draft; neither that draft nor the metadata draft is deployed on the
phone or accepted as a complete original Keystore module. Its retained raw
metadata mislabeled the runtime command as build_command; the separate
`softkeymaster194-lock-tags-v1-metadata-audit.json` records that correction without
rewriting the raw result.

The same16 cases additionally pass as the actual private service UID10050
(`mce-lock-state194-v7-contract.json`). Its own native probe asserts both real
and effective UID. The fixture bus daemon alone receives a private read-only
NSS view that recognizes this test account; the normal per-UID launcher keeps
its own unchanged private view. This fixes fixture authentication without
relaxing D-Bus credentials or adding a host account. It remains a VM fixture,
not an acceptable production service identity in the application UID pool.
The offside integration draft uses the same verified transport and genuine
native key authorization; its Binder/crypto lifecycle test waits for the whole
original build17 and metadata comparison to finish and clean up.

## Integrated source validation

Current build19 integrates real file modification-time lookup and the trusted
lock-state backend. The first integrated build18 exposed a default-startup
regression: the new lock tag guard also caught adjacent allowed parameter
cases when no lock backend was configured. Its failed normal regression and
exact source snapshot are retained. Separating that switch case fixes the
problem; no phone version ever contained it.

`standard-keystore194-v11-contract.json` passes the complete existing two-UID
RSA/EC/AES/HMAC/import/provider/restart/purpose/date/nonce/lifecycle suite on19
without a lock backend. `standard-keystore194-lock-v5-contract.json` separately
passes the two configured-backend lock/restart rounds on the same19 build.
`original-keystore194-source19-four-paired-v1.json` proves all four unchanged
original creation-date and unlocked-device-required methods pass on current19,
compared with their actual whole17 failures. Original APK/config/signer/actual
UID/native mappings remain identical. MCE state is explicitly simulated by a
root-owned private VM fixture; no phone or production identity claim is made.

The whole original build17 diagnostic completed1039 methods:1020 passes and19
failures, with safe cleanup. Its counts remain unchanged; selected later fixes
are separate evidence. Hardware attestation/Gatekeeper/device identity and the
production service/account/discovery integration remain incomplete.

The attestation draft now reaches the original software Keymaster's real
`attest_key` ABI through standard asynchronous certificate-chain callbacks.
`standard-attestation194-draft-v1.json` passes an internal 79-check owner cohort
and a 10-check actual other-UID rejection cohort. Six native RSA/EC chains are
independently verified against their exported public keys, exact challenges,
software security levels and the genuine APK package/version/signer identity;
caller-supplied application identity is rejected. APK signature verification
runs again in the service from an immutable root-staged file, without loading
APK code. This remains an isolated VM prototype, not production discovery or
a phone install. The original library's EC intermediate is expired: its actual
OpenSSL date-validation failure remains in
`standard-attestation194-draft-v1-independent.json`, whose overall `passed` is
false. Signature and identity checks do not turn that into production trust.

Actual original `KeyAttestationTest` rerun v2 completes all13 methods with8
pass and5 fail events and full cleanup. Unique-ID permission and both oversized
challenge methods now pass; software DeviceLocked and missing device-identity
service failures remain. The original APK's two basic EC/RSA methods require
secure-lockscreen eligibility and throw genuine assumptions here; the original
JUnit3 runner reports them as failures, which are retained. A real ART interface
Object-method dispatch bug previously crashed Hamcrest while formatting those
exceptions. `native/compat/patches/art-interface-object-dispatch.patch` fixes
that generic dispatch; an independent unchanged dx-generated IMT-collision
fixture fails on the baseline and passes on the actually mapped new ART.
The original13-method rerun now has no fatal result-reporting exception. No
CTS test, feature claim or skip condition was changed.


## Encoded core module and isolated package

`scripts/runtime/build-keystore-core-compat-vm.py` now produces the opt-in JKS/BKS
module from verified core/class inputs. The normal hidden-API encoder retains
all existing member/access/native flags; three JKS override/bridge methods and
one genuine D8 AtomicReference CAS helper are implementation-private. Exactly
core-oj and BKS change among the16 encoded inputs, with matching30 boot files.
The original29-method KeyStoreTest passes again with the actual new ART library
and all10 new `.art` mappings verified. The earlier VM driver that fell back to
DEX because it supplied an ISA-suffixed image path remains a separate result.

`scripts/runtime/package-keystore-core-overlay.py` packages only that source-owned
core module and matching boot over the verified property194-v2 artifact. It
checks the original encoded inputs, exact added members, all existing hidden
flags/native declarations, source hashes and every boot image. The v2 package
boundary verifies every archive member and preserves all native/runtime-JAR/
manager/property/trust-anchor bytes. Payload directories normalize to0755;
the earlier v1 strict audit found restrictive inherited baseline directory
modes, and its failure is retained. This artifact does not include the VM-only
Keystore service, attestation draft, ART dispatch patch or CA alias cleanup.
Nothing has been staged on the phone or activated as its daily component.

The new ordinary-app device-identifiers boundary is still opt-in and outside
frozen192/193 sources. It denies identifier access because the host has none of
the Android privileged/carrier/device-owner/AppOp or dangerous READ_PHONE_STATE
grant backends. APK declarations and Sailfish account UID100000 do not become
Android system grants; no host serial/IMEI/MEID is read. It is compiled, with
an ordinary-UID original AIDL/local-Parcel dispatch contract and unchanged original
method comparison queued only after the whole1039 run cleans up. Those queued
checks are not yet accepted results.


A fresh bounded read-only phone inventory confirms the existing QTI Keymaster4
and hwservicemanager processes are actual64-bit AArch64 binaries at UID1000,
with `/dev/hwbinder` present. The live backend maps the system Keymaster3/4 HIDL
libraries and vendor QSEE/QTI libraries. `hardware-readiness-vm.py` saves only
public binary/process/device metadata and hashes, verifies the known boot and
OLED brightness0, and performs no HAL RPC or credential/key storage access.
This establishes a concrete hardware-client target; it does not prove that a
SailDroid client can authenticate, call it or obtain hardware-backed keys.
The available API29 ART build tree initially lacked generated Keymaster4 HIDL
C++ headers. Original Android10 interfaces now generate31 headers with a private
HIDL10 tool; a privately extracted ARM64 Clang18 compiles the actual libc++/HIDL
client. Its17-library Android closure loads through the real translated linker
as UID65534, and5 C-boundary invalid-input calls pass without a valid hardware
RPC. No hardware-info probe is launched on the phone during the frozen queue.


## Whole combined result and formal artifact (2026-11-01 UTC)

`original-keystore194-combined-full-v1.json` completes the entire unchanged
original1039 methods:1030PASS/9FAIL, versus1020/19 in whole17. The paired auditor
requires identical ordered IDs, APK/config/signer/actual allocated UID/native8
closure and exactly10 failures becoming passes. Real client PID2348130 and the
server both map the patched ART plus all10 new boot images. No DEX fallback or
fatal runner reporting is accepted. All fixture processes/key/APK/identity/bus/
binderfs state is removed. Remaining assumptions still count as runner failures.

The v2 formal artifact packages exact property/core/ART/CA bytes with fresh
install metadata; canonical CA cleanup preserves146 unique DER anchors and
certificate bytes. The source-owned v2 deploy transaction deletes only verified
redundant aliases from a new hardlinked release and preserves the predecessor.
A genuine writable-root omission was caught by the first isolated filesystem
regression, fixed, and all17 boundary cases pass. The failed source/package/run
remain available. Old v1 deployers reject schema v2. No deployer was run on phone.
Actual formal-root original KeyStoreTest passes29/29 again with both client and
server image mappings required.

The source-owned identifier runtime overlay compiles only a new denial service
and its normal SdServices registration; all other saved class bytes and native
members remain unchanged. Canonical encoding changes only runtime.jar among16
JARs, preserves old flags, and blacklists the seven new implementation members.
Both the isolated9-check local Binder/Parcel contract and the unchanged original
DeviceIdAttestation method pass. The first own fixture incorrectly expected local
Binder.transact to serialize exceptions and failed before CTS; the corrected
fixture respects actual local propagation, with that failure retained. The
normal formal artifact then passes the same original method using its unchanged
bootstrap and normal service registration, with no injected identifier helper.
This is still not a new whole1039 count or a privileged identifier backend.

One other whole failure was a VM preparer condition: only the service had the
private MCE bus endpoint. Routing the actual client to the same explicitly
simulated unlocked root MCE fixture makes the original cannot-create-auth-bound-
key method pass. Its actual UID10000 D-Bus query is audited. Product lock/auth
code is unchanged; this neither supplies Gatekeeper nor claims a real phone
lock state. Whole counts remain1030/9. Native attestation implementation remains
in the validated offside draft until explicit source integration; the prototype
service still uses fixture UID10050 and is absent from the formal phone artifact.

## Source20 and repeatable build

The accepted combined metadata/lock/software-attestation draft is now integrated
in the source tree. The exact prior source19 and its accepted build manifest are
preserved under the evidence directory's `keystore-source-snapshots/source19-v1`.
`keystore194-source20-v1-build-boundary.json` proves that the generic
`build-vm.py --with-test-fixtures` recreates the accepted draft's exact native
ELF, every class byte and full fixture DEX. The default builder omits test and
instrumentation/bootstrap types; its service class and native bytes remain
identical (`keystore194-source20-service-v2-audit.json`). Both modes only build
VM artifacts. Neither installs a production account, supervisor, daemon,
Binder-discovery route, hardware/auth backend or phone component. Earlier
whole1030/9 and expired-native-EC trust evidence remain unchanged.
