# API29 legacy JSSE compatibility

These five repository-owned Java source overlays preserve the existing legacy
provider and its native TLS engine. The original nested repository stays intact.

The key factories track successful initialization, reject unsupported factory
parameters with the standard checked exception, and select actual private-key
entries by key/signature type and certificate issuer. Null aliases return null.
The alias algorithm follows the matching Android 10 implementation included as
a source reference.

The legacy trust factory returns the matching Android 10 `TrustManagerImpl`
for its exact configured KeyStore. Real Android native PKIX validates paths,
expiry, signatures, purpose and explicit intermediate or leaf trust anchors.
No root is silently added and no provider is removed.

The native TLS helper preserves the computed client/server `wantClientAuth` and
`needClientAuth` flags. Optional client authentication accepts a missing client
certificate only when native verification succeeds, certificate extraction
succeeds, and the actual native peer certificate count is zero. Every provided
certificate continues through the actual trust manager. Required client auth
and all client-side server authentication retain verification.

Admission evidence includes the unchanged original 409-method TLS selection
(403 PASS / 3 FAIL / 3 assumptions before; 406 PASS / 0 FAIL / 3 assumptions
after), 79 private generated-PKI/native-TLS assertions, and 38 additional EC
key interoperability assertions. These are ARM64 Linux/ART diagnostics; the
phone and complete CTS module/transport gates remain separate.
