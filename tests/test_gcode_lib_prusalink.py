"""
Tests for §10 — PrusaLink API client.

Covers:
  PrusaLinkError, PrusaLinkInfo, PrusaLinkStatus, PrusaLinkJob
  _prusalink_request, prusalink_get_version, prusalink_get_status,
  prusalink_get_job, _build_multipart, prusalink_upload
"""
from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest

import gcode_lib as gl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = "http://192.168.1.100"
API_KEY = "test-api-key-1234"


def _mock_response(body: bytes, status: int = 200):
    """Create a mock urllib response context manager."""
    resp = MagicMock()
    resp.read.return_value = body
    resp.status = status
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# PrusaLinkError
# ---------------------------------------------------------------------------


class TestPrusaLinkError:
    def test_inherits_exception(self):
        err = gl.PrusaLinkError(404, "Not found")
        assert isinstance(err, Exception)

    def test_attributes(self):
        err = gl.PrusaLinkError(500, "Internal error")
        assert err.status_code == 500
        assert err.message == "Internal error"

    def test_str(self):
        err = gl.PrusaLinkError(403, "Forbidden")
        assert "403" in str(err)
        assert "Forbidden" in str(err)


# ---------------------------------------------------------------------------
# Dataclass construction
# ---------------------------------------------------------------------------


class TestPrusaLinkDataclasses:
    def test_prusalink_info(self):
        info = gl.PrusaLinkInfo(api="2.0.0", server="2.1.0",
                                original="4.7.0", text="Original Prusa")
        assert info.api == "2.0.0"
        assert info.server == "2.1.0"
        assert info.original == "4.7.0"
        assert info.text == "Original Prusa"

    def test_prusalink_status(self):
        s = gl.PrusaLinkStatus(printer_state="IDLE", temp_nozzle=25.3,
                               temp_bed=24.1, raw={"printer": {}})
        assert s.printer_state == "IDLE"
        assert s.temp_nozzle == 25.3
        assert s.temp_bed == 24.1
        assert isinstance(s.raw, dict)

    def test_prusalink_status_none_temps(self):
        s = gl.PrusaLinkStatus(printer_state="BUSY", temp_nozzle=None,
                               temp_bed=None, raw={})
        assert s.temp_nozzle is None
        assert s.temp_bed is None

    def test_prusalink_job(self):
        j = gl.PrusaLinkJob(job_id=42, progress=55.5, time_remaining=300,
                            state="PRINTING", raw={"id": 42})
        assert j.job_id == 42
        assert j.progress == 55.5
        assert j.time_remaining == 300
        assert j.state == "PRINTING"

    def test_prusalink_job_no_active(self):
        j = gl.PrusaLinkJob(job_id=None, progress=None, time_remaining=None,
                            state="IDLE", raw={})
        assert j.job_id is None


# ---------------------------------------------------------------------------
# _prusalink_request
# ---------------------------------------------------------------------------


class TestPrusaLinkRequest:
    @patch("gcode_lib.urlopen")
    def test_get_success(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b'{"ok": true}')
        result = gl._prusalink_request(BASE_URL, API_KEY, "GET", "/api/test")
        assert result == b'{"ok": true}'
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "GET"
        assert req.full_url == f"{BASE_URL}/api/test"
        assert req.get_header("X-api-key") == API_KEY

    @patch("gcode_lib.urlopen")
    def test_put_with_data(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b"ok")
        body = b"test-data"
        gl._prusalink_request(BASE_URL, API_KEY, "PUT", "/api/files",
                              data=body, content_type="application/octet-stream")
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "PUT"
        assert req.data == body
        assert req.get_header("Content-type") == "application/octet-stream"

    @patch("gcode_lib.urlopen")
    def test_extra_headers(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b"ok")
        gl._prusalink_request(BASE_URL, API_KEY, "GET", "/test",
                              extra_headers={"X-Custom": "val"})
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("X-custom") == "val"

    @patch("gcode_lib.urlopen")
    def test_trailing_slash_stripped(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b"ok")
        gl._prusalink_request(BASE_URL + "///", API_KEY, "GET", "/api/test")
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == f"{BASE_URL}/api/test"

    @patch("gcode_lib.urlopen")
    def test_timeout_passed(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b"ok")
        gl._prusalink_request(BASE_URL, API_KEY, "GET", "/test", timeout=5.0)
        assert mock_urlopen.call_args[1]["timeout"] == 5.0

    @patch("gcode_lib.urlopen")
    def test_http_error(self, mock_urlopen):
        from urllib.error import HTTPError
        exc = HTTPError("http://test", 404, "Not Found", {}, io.BytesIO(b"gone"))
        mock_urlopen.side_effect = exc
        with pytest.raises(gl.PrusaLinkError) as exc_info:
            gl._prusalink_request(BASE_URL, API_KEY, "GET", "/missing")
        assert exc_info.value.status_code == 404
        assert "gone" in exc_info.value.message

    @patch("gcode_lib.urlopen")
    def test_http_error_unreadable_body(self, mock_urlopen):
        from urllib.error import HTTPError
        bad_fp = MagicMock()
        bad_fp.read.side_effect = IOError("broken")
        exc = HTTPError("http://test", 500, "Server Error", {}, bad_fp)
        mock_urlopen.side_effect = exc
        with pytest.raises(gl.PrusaLinkError) as exc_info:
            gl._prusalink_request(BASE_URL, API_KEY, "GET", "/fail")
        assert exc_info.value.status_code == 500

    @patch("gcode_lib.urlopen")
    def test_url_error(self, mock_urlopen):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")
        with pytest.raises(gl.PrusaLinkError) as exc_info:
            gl._prusalink_request(BASE_URL, API_KEY, "GET", "/test")
        assert exc_info.value.status_code == 0
        assert "Connection refused" in exc_info.value.message

    @patch("gcode_lib.urlopen")
    def test_timeout_error(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError()
        with pytest.raises(gl.PrusaLinkError) as exc_info:
            gl._prusalink_request(BASE_URL, API_KEY, "GET", "/test")
        assert exc_info.value.status_code == 0
        assert "timed out" in exc_info.value.message.lower()


# ---------------------------------------------------------------------------
# prusalink_get_version
# ---------------------------------------------------------------------------


class TestPrusaLinkGetVersion:
    @patch("gcode_lib.urlopen")
    def test_basic(self, mock_urlopen):
        payload = json.dumps({
            "api": "2.0.0",
            "server": "2.1.2",
            "original": "4.7.0-RC1",
            "text": "PrusaLink",
        }).encode()
        mock_urlopen.return_value = _mock_response(payload)
        info = gl.prusalink_get_version(BASE_URL, API_KEY)
        assert isinstance(info, gl.PrusaLinkInfo)
        assert info.api == "2.0.0"
        assert info.server == "2.1.2"
        assert info.original == "4.7.0-RC1"
        assert info.text == "PrusaLink"

    @patch("gcode_lib.urlopen")
    def test_missing_fields_default_empty(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b"{}")
        info = gl.prusalink_get_version(BASE_URL, API_KEY)
        assert info.api == ""
        assert info.server == ""
        assert info.original == ""
        assert info.text == ""

    @patch("gcode_lib.urlopen")
    def test_custom_timeout(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b"{}")
        gl.prusalink_get_version(BASE_URL, API_KEY, timeout=3.0)
        assert mock_urlopen.call_args[1]["timeout"] == 3.0


# ---------------------------------------------------------------------------
# prusalink_get_status
# ---------------------------------------------------------------------------


class TestPrusaLinkGetStatus:
    @patch("gcode_lib.urlopen")
    def test_basic(self, mock_urlopen):
        payload = json.dumps({
            "printer": {
                "state": "PRINTING",
                "temp_nozzle": 215.0,
                "temp_bed": 60.0,
            }
        }).encode()
        mock_urlopen.return_value = _mock_response(payload)
        status = gl.prusalink_get_status(BASE_URL, API_KEY)
        assert isinstance(status, gl.PrusaLinkStatus)
        assert status.printer_state == "PRINTING"
        assert status.temp_nozzle == 215.0
        assert status.temp_bed == 60.0
        assert "printer" in status.raw

    @patch("gcode_lib.urlopen")
    def test_missing_printer_key(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b"{}")
        status = gl.prusalink_get_status(BASE_URL, API_KEY)
        assert status.printer_state == "UNKNOWN"
        assert status.temp_nozzle is None
        assert status.temp_bed is None


# ---------------------------------------------------------------------------
# prusalink_get_job
# ---------------------------------------------------------------------------


class TestPrusaLinkGetJob:
    @patch("gcode_lib.urlopen")
    def test_active_job(self, mock_urlopen):
        payload = json.dumps({
            "id": 7,
            "progress": 42.5,
            "time_remaining": 1200,
            "state": "PRINTING",
        }).encode()
        mock_urlopen.return_value = _mock_response(payload)
        job = gl.prusalink_get_job(BASE_URL, API_KEY)
        assert isinstance(job, gl.PrusaLinkJob)
        assert job.job_id == 7
        assert job.progress == 42.5
        assert job.time_remaining == 1200
        assert job.state == "PRINTING"

    @patch("gcode_lib.urlopen")
    def test_no_job(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b'{"state": "IDLE"}')
        job = gl.prusalink_get_job(BASE_URL, API_KEY)
        assert job.job_id is None
        assert job.progress is None
        assert job.time_remaining is None
        assert job.state == "IDLE"

    @patch("gcode_lib.urlopen")
    def test_missing_state_defaults(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b"{}")
        job = gl.prusalink_get_job(BASE_URL, API_KEY)
        assert job.state == "UNKNOWN"


# ---------------------------------------------------------------------------
# _build_multipart
# ---------------------------------------------------------------------------


class TestBuildMultipart:
    def test_structure(self):
        body, ct = gl._build_multipart(
            fields={"key": "value"},
            file_field="file",
            file_name="test.gcode",
            file_data=b"G28\nG1 X10\n",
        )
        assert b"multipart/form-data" in ct.encode()
        assert b"boundary=" in ct.encode()
        boundary = ct.split("boundary=")[1]
        assert f"--{boundary}".encode() in body
        assert f"--{boundary}--".encode() in body
        assert b'name="key"' in body
        assert b"value" in body
        assert b'name="file"' in body
        assert b'filename="test.gcode"' in body
        assert b"G28\nG1 X10\n" in body

    def test_custom_content_type(self):
        body, ct = gl._build_multipart(
            fields={},
            file_field="file",
            file_name="test.gcode",
            file_data=b"data",
            file_content_type="text/plain",
        )
        assert b"Content-Type: text/plain" in body

    def test_multiple_fields(self):
        body, _ = gl._build_multipart(
            fields={"a": "1", "b": "2"},
            file_field="file",
            file_name="f.gcode",
            file_data=b"",
        )
        assert b'name="a"' in body
        assert b'name="b"' in body


# ---------------------------------------------------------------------------
# prusalink_upload
# ---------------------------------------------------------------------------


class TestPrusaLinkUpload:
    @patch("gcode_lib._prusalink_request")
    def test_basic_upload(self, mock_req, tmp_path):
        mock_req.return_value = b""
        gcode = tmp_path / "tower.gcode"
        gcode.write_text("G28\nG1 X10\n")

        result = gl.prusalink_upload(BASE_URL, API_KEY, str(gcode))
        assert result == "tower.gcode"

        mock_req.assert_called_once()
        args = mock_req.call_args
        assert args[0][0] == BASE_URL
        assert args[0][1] == API_KEY
        assert args[0][2] == "PUT"
        assert "/api/v1/files/usb/tower.gcode" in args[0][3]

    @patch("gcode_lib._prusalink_request")
    def test_print_after_upload(self, mock_req, tmp_path):
        mock_req.return_value = b""
        gcode = tmp_path / "test.gcode"
        gcode.write_text("G28\n")

        gl.prusalink_upload(BASE_URL, API_KEY, str(gcode),
                            print_after_upload=True)
        headers = mock_req.call_args[1]["extra_headers"]
        assert headers["Print-After-Upload"] == "1"

    @patch("gcode_lib._prusalink_request")
    def test_no_print_after_upload(self, mock_req, tmp_path):
        mock_req.return_value = b""
        gcode = tmp_path / "test.gcode"
        gcode.write_text("G28\n")

        gl.prusalink_upload(BASE_URL, API_KEY, str(gcode),
                            print_after_upload=False)
        headers = mock_req.call_args[1]["extra_headers"]
        assert "Print-After-Upload" not in headers

    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            gl.prusalink_upload(BASE_URL, API_KEY, "/nonexistent/file.gcode")

    @patch("gcode_lib._prusalink_request")
    def test_custom_timeout(self, mock_req, tmp_path):
        mock_req.return_value = b""
        gcode = tmp_path / "test.gcode"
        gcode.write_text("G28\n")

        gl.prusalink_upload(BASE_URL, API_KEY, str(gcode), timeout=60.0)
        assert mock_req.call_args[1]["timeout"] == 60.0

    @patch("gcode_lib._prusalink_request")
    def test_content_length_header(self, mock_req, tmp_path):
        mock_req.return_value = b""
        gcode = tmp_path / "test.gcode"
        gcode.write_text("G28\n")

        gl.prusalink_upload(BASE_URL, API_KEY, str(gcode))
        headers = mock_req.call_args[1]["extra_headers"]
        assert "Content-Length" in headers
        assert int(headers["Content-Length"]) == len(b"G28\n")
