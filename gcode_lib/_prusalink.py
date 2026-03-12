"""PrusaLink API client — standalone submodule.

This module is fully independent: it uses only stdlib imports and has
zero dependencies on the rest of gcode_lib.
"""
from __future__ import annotations

import json
import sys
import uuid
from http.client import InvalidURL
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class PrusaLinkError(Exception):
    """Raised when a PrusaLink API call fails.

    Attributes
    ----------
    status_code: HTTP status code (0 for connection/timeout errors).
    message:     Human-readable error description.
    """

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"PrusaLink error {status_code}: {message}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PrusaLinkInfo:
    """Printer identification from ``GET /api/version``.

    Attributes
    ----------
    api:      API version string.
    server:   Server version string.
    original: Original PrusaLink version.
    text:     Human-readable description.
    """
    api: str
    server: str
    original: str
    text: str


@dataclass
class PrusaLinkStatus:
    """Printer status from ``GET /api/v1/status``.

    Attributes
    ----------
    printer_state: Current state (``"IDLE"``, ``"PRINTING"``, ``"BUSY"``, ...).
    temp_nozzle:   Current nozzle temperature in deg-C (or ``None``).
    temp_bed:      Current bed temperature in deg-C (or ``None``).
    raw:           Full JSON response for extensibility.
    """
    printer_state: str
    temp_nozzle: Optional[float]
    temp_bed: Optional[float]
    raw: dict


@dataclass
class PrusaLinkJob:
    """Active job info from ``GET /api/v1/job``.

    Attributes
    ----------
    job_id:         Numeric job ID (or ``None`` if no job).
    progress:       Print progress 0-100 (or ``None``).
    time_remaining: Estimated seconds remaining (or ``None``).
    state:          Job state string.
    raw:            Full JSON response for extensibility.
    """
    job_id: Optional[int]
    progress: Optional[float]
    time_remaining: Optional[int]
    state: str
    raw: dict


# ---------------------------------------------------------------------------
# Internal HTTP helper
# ---------------------------------------------------------------------------


def _prusalink_request(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    data: Optional[bytes] = None,
    content_type: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
) -> bytes:
    """Make an HTTP request to PrusaLink and return the raw response body.

    Parameters
    ----------
    base_url:       Printer base URL, e.g. ``"http://192.168.1.100"``.
    api_key:        PrusaLink API key (sent as ``X-Api-Key`` header).
    method:         HTTP method (``"GET"``, ``"PUT"``, ``"POST"``, ``"DELETE"``).
    path:           API path, e.g. ``"/api/version"``.
    data:           Optional request body bytes.
    content_type:   Optional ``Content-Type`` header value.
    extra_headers:  Additional headers to include.
    timeout:        Request timeout in seconds.

    Returns
    -------
    bytes
        Raw response body.

    Raises
    ------
    PrusaLinkError
        On HTTP errors or connection failures.
    """
    url = base_url.rstrip("/") + path
    headers: Dict[str, str] = {"X-Api-Key": api_key}
    if content_type:
        headers["Content-Type"] = content_type
    if extra_headers:
        headers.update(extra_headers)

    try:
        req = Request(url, data=data, headers=headers, method=method)
    except ValueError as exc:
        raise PrusaLinkError(0, f"Invalid URL: {exc}") from exc
    # Look up urlopen via the parent package so mock.patch("gcode_lib.urlopen") works.
    _urlopen = sys.modules[__name__.rpartition(".")[0]].urlopen
    try:
        with _urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise PrusaLinkError(exc.code, body or str(exc)) from exc
    except URLError as exc:
        raise PrusaLinkError(0, str(exc.reason)) from exc
    except TimeoutError as exc:
        raise PrusaLinkError(0, "Connection timed out") from exc
    except InvalidURL as exc:
        raise PrusaLinkError(0, f"Invalid URL: {exc}") from exc


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------


def prusalink_get_version(
    base_url: str,
    api_key: str,
    timeout: float = 10.0,
) -> PrusaLinkInfo:
    """Query printer identification via ``GET /api/version``.

    This is the lightest endpoint and works well as a connectivity test.

    Parameters
    ----------
    base_url: Printer base URL.
    api_key:  PrusaLink API key.
    timeout:  Request timeout in seconds.

    Returns
    -------
    PrusaLinkInfo
    """
    body = _prusalink_request(base_url, api_key, "GET", "/api/version",
                              timeout=timeout)
    d = json.loads(body)
    return PrusaLinkInfo(
        api=d.get("api", ""),
        server=d.get("server", ""),
        original=d.get("original", ""),
        text=d.get("text", ""),
    )


def prusalink_get_status(
    base_url: str,
    api_key: str,
    timeout: float = 10.0,
) -> PrusaLinkStatus:
    """Query current printer status via ``GET /api/v1/status``.

    Parameters
    ----------
    base_url: Printer base URL.
    api_key:  PrusaLink API key.
    timeout:  Request timeout in seconds.

    Returns
    -------
    PrusaLinkStatus
    """
    body = _prusalink_request(base_url, api_key, "GET", "/api/v1/status",
                              timeout=timeout)
    d = json.loads(body)
    printer = d.get("printer", {})
    return PrusaLinkStatus(
        printer_state=printer.get("state", "UNKNOWN"),
        temp_nozzle=printer.get("temp_nozzle"),
        temp_bed=printer.get("temp_bed"),
        raw=d,
    )


def prusalink_get_job(
    base_url: str,
    api_key: str,
    timeout: float = 10.0,
) -> PrusaLinkJob:
    """Query active print job via ``GET /api/v1/job``.

    Parameters
    ----------
    base_url: Printer base URL.
    api_key:  PrusaLink API key.
    timeout:  Request timeout in seconds.

    Returns
    -------
    PrusaLinkJob
    """
    body = _prusalink_request(base_url, api_key, "GET", "/api/v1/job",
                              timeout=timeout)
    d = json.loads(body)
    return PrusaLinkJob(
        job_id=d.get("id"),
        progress=d.get("progress"),
        time_remaining=d.get("time_remaining"),
        state=d.get("state", "UNKNOWN"),
        raw=d,
    )


def _build_multipart(
    fields: Dict[str, str],
    file_field: str,
    file_name: str,
    file_data: bytes,
    file_content_type: str = "application/octet-stream",
) -> Tuple[bytes, str]:
    """Build a multipart/form-data body from fields and one file.

    Returns ``(body_bytes, content_type_header)`` including the boundary.
    """
    boundary = uuid.uuid4().hex
    parts: List[bytes] = []
    for key, val in fields.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{val}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{file_field}";'
        f' filename="{file_name}"\r\n'
        f"Content-Type: {file_content_type}\r\n\r\n".encode()
    )
    parts.append(file_data)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    ct = f"multipart/form-data; boundary={boundary}"
    return body, ct


def prusalink_upload(
    base_url: str,
    api_key: str,
    gcode_path: str,
    print_after_upload: bool = False,
    timeout: float = 120.0,
) -> str:
    """Upload a G-code file to the printer via PrusaLink.

    Uses ``PUT /api/v1/files/usb/<filename>`` with the raw file body.

    Parameters
    ----------
    base_url:           Printer base URL.
    api_key:            PrusaLink API key.
    gcode_path:         Local path to the ``.gcode`` file.
    print_after_upload: If ``True``, start printing immediately after upload.
    timeout:            Request timeout in seconds (uploads can be slow).

    Returns
    -------
    str
        The filename as stored on the printer.

    Raises
    ------
    PrusaLinkError
        On HTTP or connection errors.
    FileNotFoundError
        If *gcode_path* does not exist.
    """
    p = Path(gcode_path)
    if not p.is_file():
        raise FileNotFoundError(f"G-code file not found: {gcode_path}")

    file_data = p.read_bytes()
    filename = p.name
    # URL-encode filename to support spaces and other reserved URL characters.
    path = f"/api/v1/files/usb/{quote(filename, safe='')}"

    extra_headers: Dict[str, str] = {
        "Content-Length": str(len(file_data)),
        "Content-Type": "application/octet-stream",
    }
    if print_after_upload:
        extra_headers["Print-After-Upload"] = "1"

    # Look up via parent package so mock.patch("gcode_lib._prusalink_request") works.
    _req_fn = sys.modules[__name__.rpartition(".")[0]]._prusalink_request
    _req_fn(
        base_url, api_key, "PUT", path,
        data=file_data,
        extra_headers=extra_headers,
        timeout=timeout,
    )
    return filename
