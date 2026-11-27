# Public hardware identity

`hardware_identity.py` provisions five public product fields in the private
component's `build.prop`. Android `Build`, the native property table and the
component's `getprop` consequently share one source. It changes no APK and has
no application-specific branch.

Capture with `capture-hardware-identity-phone.py` on the actual Sailfish target,
through the existing VM/SSH transport. The capture reads public manufacturer,
brand, model, product and device names plus the hardware adaptation identity;
it does not read serial, IMEI, account or persistent device identifiers. Feed
the resulting JSON to `package-component.py --hardware-profile PROFILE.json`
when packaging for that phone. An unprofiled generic component retains its
existing generic metadata; it does not guess a model from a hostname.

The resolver selects one complete, hardware-confirmed vendor group before the
system group. This accommodates a sibling system image, such as `sargo` system
properties on a hardware adaptation and vendor image that both report `bonito`.
It rejects partial, ambiguous, malformed and unconfirmed inputs. Public identity
is provisioned per target: capture a new profile when moving to another device.

The Android API level, compatibility build fingerprint, signing tags, security
patch metadata, CPU ABI and service permissions retain their component values.
They describe the hosted Android userland. Model correction does not claim a
stock Android build or device certification.

`check-hardware-identity.py` exercises coherent selection and invalid input.
`DeviceModelContract.java` is an ordinary application-loader Java main class.
Compile it against API29, DEX it, and run it through each component's real
`bin/dalvikvm`, supplying the five expected fields. Independently compare the
same values through that component's `bin/getprop` as the ordinary phone user.
Use a device lock and the existing display cleanup during phone checks. An
unchanged Java/native library set needs no APK AOT rebuild for this profile.

The R318b runtime adds a generic public hardware startup marker; its matching
QQ AOT pair was rebuilt and verified separately. Existing QQ installations may
retain an encoded model cache; the accepted one-time, backed-up narrow refresh
and authorized logout/login are documented in
`docs/QQ-DEVICE-MODEL-R318-2026-11-04.md`. Product code does not target QQ.

The r318 device evidence is in
`build/evidence/device-model318-20261104/`; its baseline and candidate contracts
use the same unchanged ART/framework files and the same boot.
