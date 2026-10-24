#!/usr/bin/env python3
"""Rebuild LastPass CLI 1.6.1 with the verified GlobalSign E46 root pin."""
import base64
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

SOURCE_URL = "https://github.com/lastpass/lastpass-cli/releases/download/v1.6.1/lastpass-cli-1.6.1.tar.gz"
SOURCE_SHA256 = "5e4ff5c9fef8aa924547c565c44e5b4aa31e63d642873847b8e40ce34558a5e1"
ROOT_URL = "https://secure.globalsign.com/cacert/roote46.crt"
ROOT_SHA256 = "cbb9c44d84b8043e1050ea31a69f514955d7bfd2e2c6b49301019ad61d9f5058"
ROOT_PIN = "4EoCLOMvTM8sf2BGKHuCijKpCfXnUUR/g/0scfb9gXM="
PATCHES = [
    ("31a4ad5f735933ff8e96403103d5b4f61faee945", "a4c2a16fd47942a511c0ebbce08bee5ffdb0d6141f6c9b60ce397db9e207d8be"),
    ("95fff9accc5832264e31af3f54f49af461339693", "5d7559511b1814c6f9d8cccc02b7c5dbf8a4e6d2927a94cf76d090cc45a47dd2"),
]


def download(url, path, digest):
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError(f"SHA256 mismatch for {url}")
    path.write_bytes(data)


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    if sys.version_info < (3, 12):
        raise SystemExit("This installer requires Python 3.12 or later.")
    executable = shutil.which("lpass")
    if not executable:
        raise SystemExit("Install the official lastpass-cli package first.")
    target = Path(executable).resolve()
    brew = shutil.which("brew")
    if not brew:
        raise SystemExit("This repair installer requires macOS Homebrew.")
    for command in ("cmake", "patch", "pkg-config"):
        if not shutil.which(command):
            raise SystemExit(f"Missing build prerequisite: {command}. Run brew install cmake pkgconf.")
    package = Path(subprocess.check_output([brew, "--prefix", "lastpass-cli"], text=True).strip())
    if target != (package / "bin/lpass").resolve():
        raise SystemExit("Refusing to replace lpass outside the official Homebrew lastpass-cli package.")
    prefixes = {name: subprocess.check_output([brew, "--prefix", name], text=True).strip()
                for name in ("openssl@3", "curl")}
    openssl = str(Path(prefixes["openssl@3"]) / "bin/openssl")
    backend = subprocess.check_output([str(Path(prefixes["curl"]) / "bin/curl-config"), "--ssl-backends"], text=True).strip()
    if backend != "OpenSSL":
        raise SystemExit("The pin callback requires Homebrew curl with its OpenSSL backend.")
    if any("DO_NOT_ENABLE_ME_MITM_PROXY_FOR_DEBUGGING_ONLY" in os.environ.get(name, "")
           or "TEST_BUILD" in os.environ.get(name, "") for name in ("CFLAGS", "CPPFLAGS", "CXXFLAGS")):
        raise SystemExit("Refusing compiler flags that bypass production TLS checks.")
    with tempfile.TemporaryDirectory(prefix="lastpass-tls-repair-") as work:
        work = Path(work)
        root = work / "root.der"
        download(ROOT_URL, root, ROOT_SHA256)
        public = subprocess.check_output([openssl, "x509", "-inform", "DER", "-in", str(root), "-pubkey", "-noout"])
        der = subprocess.check_output([openssl, "pkey", "-pubin", "-outform", "DER"], input=public)
        if base64.b64encode(hashlib.sha256(der).digest()).decode() != ROOT_PIN:
            raise RuntimeError("Verified root SPKI does not match the reviewed pin")
        archive = work / "source.tar.gz"
        download(SOURCE_URL, archive, SOURCE_SHA256)
        with tarfile.open(archive) as source_archive:
            source_archive.extractall(work, filter="data")
        source = work / "lastpass-cli-1.6.1"
        for commit, digest in PATCHES:
            patch = work / f"{commit}.patch"
            download(f"https://github.com/lastpass/lastpass-cli/commit/{commit}.patch?full_index=1", patch, digest)
            run("patch", "-p1", "-i", str(patch), cwd=source)
        pins = source / "pins.h"
        text = pins.read_text()
        anchor = "const char *PK_PINS[] = {"
        if text.count(anchor) != 1:
            raise RuntimeError("Upstream pin declaration changed")
        pins.write_text(text.replace(anchor, anchor + f'\n\t/* Verified GlobalSign Root E46 (TLS). */\n\t"{ROOT_PIN}",'))
        http = (source / "http.c").read_text()
        for check in ("if (!preverify_ok)", "CURLOPT_SSL_VERIFYHOST, 2", "CURLOPT_SSL_VERIFYPEER, 1", "CURLOPT_SSL_CTX_FUNCTION, pin_keys"):
            if check not in http:
                raise RuntimeError(f"Missing upstream TLS check: {check}")
        build = work / "build"
        run("cmake", "-S", str(source), "-B", str(build), "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
            f'-DOPENSSL_ROOT_DIR={prefixes["openssl@3"]}',
            f'-DCURL_INCLUDE_DIR={prefixes["curl"]}/include',
            f'-DCURL_LIBRARY={prefixes["curl"]}/lib/libcurl.dylib')
        run("cmake", "--build", str(build), "--target", "lpass", "--parallel", "4")
        binary = build / "lpass"
        run(str(binary), "--version")
        # Preserve the package-managed path and launcher. A package upgrade can
        # replace this repair; rerun this documented installer until upstream fixes pins.
        staged = target.with_name("lpass.tls-repair")
        shutil.copy2(binary, staged)
        staged.chmod(0o755)
        os.replace(staged, target)
        print(f"Installed verified E46 pin repair: {target}")


if __name__ == "__main__":
    main()
