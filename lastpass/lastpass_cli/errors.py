"""Safe upstream failure diagnostics without exposing vault output."""
TLS_FAILURE = "Error: SSL peer certificate or SSH remote key was not OK."


def command_error(command: str, returncode: int, stderr: str) -> str:
    """Expose only recognized public diagnostics; never arbitrary output."""
    message = f"{command} command failed (exit {returncode})"
    if stderr.strip() == TLS_FAILURE:
        message += (
            ": TLS certificate verification failed. Check the certificate chain, "
            "hostname, and lpass certificate pins; never disable verification."
        )
    return message
