# MediaPlayer regression inputs

Each directory contains an independent ordinary Android activity with the same
package/class name. Build and sign separate fixture APKs for target SDK 29 and
34; never combine the activities into one APK. These are temporary test apps,
not phone launcher inventory.

- `fd`: actual bundled VP8/Vorbis playback into TextureView, stable paused
  position, one seek completion and EOS. Bundle the generated `clip.webm` asset.
- `http-errors`: a real loopback HTTP 404 and an untrusted HTTPS certificate
  must each deliver one error, with no prepared event or decoded frame.
- `tls-host`: a test-only KeyStore trusts the bundled fixture certificate in
  this process. IP endpoint plus correct Host plays to EOS; a wrong Host and
  the original untrusted certificate policy both reject it. Android audio focus
  must return an explicit denial. This fixture never modifies system trust.

The checked build/launch drivers, generated clips, APK hashes, endpoint logs and
per-SDK results for this implementation are retained under
`build/evidence/qq-media-player312-20261103-v1/`. HTTP servers are ephemeral and
loopback-only on the phone through a bounded SSH reverse forward. Require the
request header and actual byte ranges on the server as well as player events.

Retain failed results. In particular, the TLS host runs' identity/trust checks
pass while their additional SNI assertion fails: the current URLConnection
transport sends no SNI in this IP-endpoint case. `identity-trust-results.json`
states the narrower proven result. Do not relabel those overall runs as passed.

Device drivers must acquire `scripts/devlock.sh`, verify Sailfish boot/component
and payload hashes, use an independent OLED blank watchdog, remove only their
owned fixture process/app, and verify MCE off plus actual brightness zero.
Real QQ acceptance is a separate physical-touch video and IME test.
