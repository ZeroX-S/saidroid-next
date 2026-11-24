# Third-party source and notices

The Apache-2.0 license at the repository root applies to original SaiDroid contributions unless a file states otherwise. Imported and derived code retains its existing copyright headers and licenses; it is not relicensed by the root license.

- `third_party/art-standalone`: Android Translation Layer standalone ART, pinned to the commit in `third-party-sources.json`. Includes AOSP components under their respective notices and OpenJDK-derived GPLv2 code with the Classpath exception. Local filesystem/source adjustments are recorded in `patches/third-party/`.
- `third_party/bionic_translation`: Android Translation Layer bionic compatibility implementation; pinned commit and local linker modifications are provided. Preserve upstream notices, including BSD-licensed bionic linker material.
- `third_party/vixl` and `third_party/vixl-aosp`: Linaro/AOSP VIXL sources, under their upstream licenses.
- `scripts/api28/public-api-compat`, `scripts/api28/sip-service-compat`, `native/rtp`, `scripts/device/sip`, `scripts/api29/core`, and compatibility trees: include AOSP (`android-9.0.0_r61` and standalone libcore) / OpenJDK / other upstream sources. File headers and accompanying `sources.json` manifests identify their applicable terms and upstream SHA-256 checksums. Relevant libcore/OpenJDK notices are included under `LICENSES/`.
- `native/ime`: uses Maliit interface XML under LGPL-2.1; source attribution and license are retained in that directory.
- `native/host/third_party`: nlohmann JSON, under the included MIT license.
- Android framework/library build inputs are fetched separately from their recorded upstream URLs and checksums; this repository does not distribute the commercial application APKs used in testing.

Runtime RPMs are a multi-license aggregate. They also contain separately supplied target-host support libraries and Android runtime/build inputs identified by the bundled provenance. They are not wholly licensed as Apache-2.0. The RPM reports its host dependency requirements; target system libraries and proprietary application APKs are not granted a new license by this project.

The repository excludes the old HotSpot/dex2jvm framework binary and legacy application binaries. Historical references in developer scripts are not a grant to redistribute those separate inputs.
