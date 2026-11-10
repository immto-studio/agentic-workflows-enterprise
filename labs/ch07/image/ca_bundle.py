"""Larkspur's private root CA, added to the CA bundle the runtime provides, and kept current.

Chapters 7 and 8. Larkspur's internal services (the model gateway, the MCP server, the collector)
present certificates from Larkspur's private CA. On Foundry the runtime may set a bundle of its
own: with egress controls on, its egress proxy inspects TLS, SSL_CERT_FILE names a bundle that
holds the proxy's CA, and that CA rotates while the sandbox runs. Microsoft's way to add your own
roots is to build one bundle at process start from the runtime's and yours (Add guardrails to a
hosted agent, "Certificate handling", learn.microsoft.com, 2026-09-24):

    cat "$SSL_CERT_FILE" /app/custom-roots.pem > /tmp/runtime-ca-bundle.pem

`TrustBundle` builds that file, and builds it again whenever either input changes. SSL_CERT_FILE,
which httpx and httpx2 read, and REQUESTS_CA_BUNDLE, which requests reads under the OTLP exporter,
then name it. When the runtime sets no SSL_CERT_FILE, the base is certifi's bundle, the one those
clients trust by default. Without a roots file nothing changes, as in chapter 7's image, where
Google's Agent Gateway checks the destinations' certificates against Larkspur's CA itself.
"""

from __future__ import annotations

import os
import ssl
import tempfile
import threading
from collections.abc import MutableMapping
from pathlib import Path

import certifi

ROOTS_ENV = "CUSTOM_ROOTS_FILE"
DEFAULT_ROOTS = "/app/custom-roots.pem"  # where labs/ch08/image/Dockerfile puts Larkspur's root
VARIABLES = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")  # what the image's TLS clients read


class TrustBundle:
    """The runtime's CA bundle, or certifi's, followed by Larkspur's roots, in one file."""

    def __init__(self, base: Path, roots: Path, combined: Path,
                 environ: MutableMapping[str, str] = os.environ) -> None:
        self.base, self.roots, self.combined, self.environ = base, roots, combined, environ
        self._written: bytes | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls, environ: MutableMapping[str, str] = os.environ,
                         combined: Path | None = None) -> TrustBundle | None:
        """The bundle this process builds, or None without a roots file.

        Call it once, before the first refresh(): it reads the runtime's SSL_CERT_FILE, which
        refresh() then points at the combined file, /tmp/runtime-ca-bundle.pem unless `combined`
        says otherwise.
        """
        named = environ.get(ROOTS_ENV, "").strip()
        roots = Path(named or DEFAULT_ROOTS)
        if not roots.is_file():
            if named:
                raise FileNotFoundError(f"{ROOTS_ENV} names {roots}, which is not a file")
            return None
        base = Path(environ.get("SSL_CERT_FILE") or certifi.where())
        return cls(base, roots, combined or Path(tempfile.gettempdir()) / "runtime-ca-bundle.pem", environ)

    def refresh(self) -> bool:
        """Rewrite the combined bundle if an input changed, and point the variables at it.

        Returns whether it wrote. A roots file without a certificate raises; so does a combination
        that doesn't load as a CA bundle, such as one built from a runtime bundle caught
        half-written. Either way the previous file stays in place.
        """
        with self._lock:
            base = self.base.read_bytes()
            source = base + (b"" if base.endswith(b"\n") else b"\n") + self.roots.read_bytes()
            if source == self._written:
                return False
            ssl.create_default_context(cafile=str(self.roots))  # the base's certificates must not hide an empty root
            staged = self.combined.with_name(self.combined.name + ".new")
            staged.write_bytes(source)
            ssl.create_default_context(cafile=str(staged))  # raises unless it holds usable certificates
            os.replace(staged, self.combined)
            self._written = source
            for name in VARIABLES:
                self.environ[name] = str(self.combined)
            return True
