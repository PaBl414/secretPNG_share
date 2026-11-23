"""Stable command-line error messages."""


class AppError(Exception):
    """Failure with a stable CLI exit code."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


LIMIT = "File or image exceeds supported limits."
INVALID_PNG = "Invalid or unsupported PNG."
INVALID_CONTAINER = "Invalid secretPNG container."
NO_HEADER = "No secretPNG header found."
BAD_PASSWORD = "Incorrect password or damaged header."
INTEGRITY = "Payload integrity check failed."
OUTPUT_EXISTS = "Output already exists."
FILE_ERROR = "Cannot read input or write output."
NETWORK_ERROR = "LAN connection failed or timed out."
REJECTED = "LAN transfer rejected or corrupted."
INVALID_ARGS = "Invalid arguments. See --help."
PASSWORD_REQUIRED = "Password required or confirmation mismatch."
