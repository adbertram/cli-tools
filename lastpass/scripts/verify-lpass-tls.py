#!/usr/bin/env python3
"""Prove installed lpass rejects an untrusted certificate before sending data."""
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading


def main():
    with tempfile.TemporaryDirectory(prefix="lpass-tls-probe-") as directory:
        work = Path(directory)
        openssl = Path(subprocess.check_output(["brew", "--prefix", "openssl@3"], text=True).strip()) / "bin/openssl"
        subprocess.run([str(openssl), "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(work / "key.pem"), "-out", str(work / "cert.pem"),
                        "-days", "1", "-subj", "/CN=lastpass.com", "-addext", "subjectAltName=DNS:lastpass.com"],
                       check=True, capture_output=True)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(work / "cert.pem", work / "key.pem")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(15)
        port = listener.getsockname()[1]
        state = {"certificate_presented": False, "application_bytes": 0}
        errors = []

        def serve():
            try:
                client, _ = listener.accept()
                with client:
                    headers = b""
                    while b"\r\n\r\n" not in headers:
                        chunk = client.recv(4096)
                        if not chunk:
                            raise RuntimeError("Proxy CONNECT closed early")
                        headers += chunk
                    if not headers.startswith(b"CONNECT lastpass.com:443 "):
                        raise RuntimeError("Unexpected proxy request")
                    client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                    state["certificate_presented"] = True
                    try:
                        with context.wrap_socket(client, server_side=True) as secured:
                            state["application_bytes"] = len(secured.recv(4096))
                    except ssl.SSLError:
                        pass  # The peer must abort certificate verification.
            except Exception as error:
                errors.append(str(error))
            finally:
                listener.close()

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        environment = {**os.environ, "LPASS_HOME": str(work / "vault"), "LPASS_AGENT_DISABLE": "1",
                       "LPASS_DISABLE_PINENTRY": "1", "https_proxy": f"http://127.0.0.1:{port}",
                       "HTTPS_PROXY": f"http://127.0.0.1:{port}", "NO_PROXY": "", "no_proxy": ""}
        result = subprocess.run([shutil.which("lpass"), "login", "tls-probe@example.invalid"],
                                input="", text=True, capture_output=True, env=environment, timeout=25)
        worker.join(timeout=20)
        if errors or worker.is_alive():
            raise RuntimeError(f"Probe transport failed: {errors}")
        if (result.returncode != 1 or "SSL peer certificate or SSH remote key was not OK" not in result.stderr
                or not state["certificate_presented"] or state["application_bytes"]):
            raise RuntimeError(f"Certificate rejection failed: exit={result.returncode}, state={state}, stderr={result.stderr!r}")
        print(json.dumps({"binary": shutil.which("lpass"), "tls_rejected": True, **state}))


if __name__ == "__main__":
    main()
