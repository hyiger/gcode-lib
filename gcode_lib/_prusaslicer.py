"""PrusaSlicer CLI helpers and INI parsing/editing — standalone submodule.

This module is fully independent: it uses only stdlib imports and has
zero dependencies on the rest of gcode_lib.
"""
from __future__ import annotations

import concurrent.futures
import configparser
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PrusaSlicerCapabilities:
    """Detected PrusaSlicer executable capabilities.

    Attributes
    ----------
    version_text:          Full version string as reported by ``--help``.
    has_export_gcode:      ``--export-gcode`` / ``-g`` flag present.
    has_load_config:       ``--load`` flag present.
    has_help_fff:          ``--help-fff`` flag present.
    supports_binary_gcode: ``--export-binary-gcode`` or ``--binary`` flag present.
    raw_help:              Full output of ``prusa-slicer --help``.
    raw_help_fff:          Output of ``prusa-slicer --help-fff``, or ``None``.
    """
    version_text: str
    has_export_gcode: bool
    has_load_config: bool
    has_help_fff: bool
    supports_binary_gcode: bool
    raw_help: str
    raw_help_fff: Optional[str]


@dataclass
class RunResult:
    """Result of a PrusaSlicer CLI invocation.

    Attributes
    ----------
    cmd:        Full command list that was executed.
    returncode: Process exit code (0 = success).
    stdout:     Captured standard output.
    stderr:     Captured standard error.
    """
    cmd: List[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """True if the process exited with code 0."""
        return self.returncode == 0


@dataclass
class SliceRequest:
    """Parameters for a single PrusaSlicer slicing operation.

    Attributes
    ----------
    input_path:          Path to the 3-D model (``.stl``, ``.3mf``, ...).
    output_path:         Desired output G-code path.
    config_ini:          Path to a PrusaSlicer ``.ini`` config file (or
                         ``None`` to use the slicer's built-in defaults).
    printer_technology:  ``"FFF"`` (default) or ``"SLA"``.
    extra_args:          Additional raw CLI arguments passed verbatim.
    """
    input_path: str
    output_path: str
    config_ini: Optional[str]
    printer_technology: str = "FFF"
    extra_args: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal template helper (local copy to avoid dependency on gcode_lib)
# ---------------------------------------------------------------------------

_TEMPLATE_VAR_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def _render_template(template_text: str, variables: Dict[str, object]) -> str:
    """Substitute ``{key}`` placeholders in *template_text* from *variables*.

    Only simple lowercase identifiers of the form ``{[a-z][a-z0-9_]*}`` are
    substituted.  Placeholders with no matching key are left unchanged.
    """
    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        key = m.group(1)
        if key in variables:
            return str(variables[key])
        return m.group(0)

    return _TEMPLATE_VAR_RE.sub(_replace, template_text)


# ---------------------------------------------------------------------------
# PrusaSlicer executable search paths
# ---------------------------------------------------------------------------

# Common executable names / paths searched by find_prusaslicer_executable.
_PS_PATHS_MACOS: List[str] = [
    "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer-console",
    "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
    "/Applications/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer-console",
]
_PS_PATHS_WIN: List[str] = [
    r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
    r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer.exe",
    r"C:\Program Files (x86)\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
    r"C:\Program Files (x86)\Prusa3D\PrusaSlicer\prusa-slicer.exe",
]
_PS_PATH_NAMES: List[str] = [
    "prusa-slicer-console",
    "prusa-slicer",
    "PrusaSlicer-console",
    "PrusaSlicer",
    "prusaslicer",
]


# ---------------------------------------------------------------------------
# PrusaSlicer CLI helpers
# ---------------------------------------------------------------------------


def find_prusaslicer_executable(
    prefer_console: bool = True,
    explicit_path: Optional[str] = None,
) -> str:
    """Locate the PrusaSlicer executable on the current machine.

    Search order
    ------------
    1. *explicit_path* if supplied (raises :class:`FileNotFoundError` if absent).
    2. Platform-specific well-known installation paths.
    3. ``PATH`` entries via :func:`shutil.which`.

    Parameters
    ----------
    prefer_console: Prefer the ``PrusaSlicer-console`` / ``prusa-slicer-console``
                    variant (no GUI) when both are available.
    explicit_path:  Override all search logic with an exact path.

    Raises
    ------
    FileNotFoundError
        If no PrusaSlicer executable can be located.
    """
    if explicit_path is not None:
        if not os.path.isfile(explicit_path):
            raise FileNotFoundError(
                f"Explicit PrusaSlicer path not found: {explicit_path!r}"
            )
        return explicit_path

    candidates: List[str] = []

    if sys.platform == "darwin":
        if prefer_console:
            candidates += _PS_PATHS_MACOS
        else:
            candidates += _PS_PATHS_MACOS[::-1]
    elif sys.platform == "win32":
        if prefer_console:
            candidates += _PS_PATHS_WIN
        else:
            candidates += _PS_PATHS_WIN[::-1]

    # Search PATH (cross-platform fallback).
    names = _PS_PATH_NAMES if prefer_console else _PS_PATH_NAMES[::-1]
    for name in names:
        found = shutil.which(name)
        if found and found not in candidates:
            candidates.append(found)

    for path in candidates:
        if os.path.isfile(path):
            return path

    raise FileNotFoundError(
        "PrusaSlicer executable not found.  Install PrusaSlicer or pass "
        "`explicit_path` to find_prusaslicer_executable()."
    )


def probe_prusaslicer_capabilities(exe: str) -> PrusaSlicerCapabilities:
    """Query a PrusaSlicer executable for its version and supported flags.

    Runs ``exe --help`` (and ``exe --help-fff`` if available) and parses the
    output to populate a :class:`PrusaSlicerCapabilities` object.

    Parameters
    ----------
    exe: Path to the PrusaSlicer executable.

    Raises
    ------
    RuntimeError
        If ``--help`` times out or the executable cannot be run.
    """
    try:
        r = subprocess.run(
            [exe, "--help"],
            capture_output=True, text=True, timeout=30,
        )
        raw_help = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"PrusaSlicer --help timed out: {exe!r}")
    except OSError as exc:
        raise RuntimeError(f"Cannot run PrusaSlicer {exe!r}: {exc}") from exc

    # Extract version string (e.g. "PrusaSlicer-2.8.0+").
    v_match = re.search(
        r"PrusaSlicer[- ]([0-9]+\.[0-9]+\.[0-9]+[^\s]*)", raw_help, re.IGNORECASE
    )
    version_text = v_match.group(0) if v_match else "unknown"

    has_export_gcode   = "--export-gcode" in raw_help or " -g " in raw_help
    has_load_config    = "--load" in raw_help
    has_help_fff       = "--help-fff" in raw_help
    supports_bgcode    = "--export-binary-gcode" in raw_help or "--binary" in raw_help

    raw_help_fff: Optional[str] = None
    if has_help_fff:
        try:
            r_fff = subprocess.run(
                [exe, "--help-fff"],
                capture_output=True, text=True, timeout=30,
            )
            raw_help_fff = r_fff.stdout + r_fff.stderr
        except (subprocess.TimeoutExpired, OSError):
            pass

    return PrusaSlicerCapabilities(
        version_text=version_text,
        has_export_gcode=has_export_gcode,
        has_load_config=has_load_config,
        has_help_fff=has_help_fff,
        supports_binary_gcode=supports_bgcode,
        raw_help=raw_help,
        raw_help_fff=raw_help_fff,
    )


def run_prusaslicer(
    exe: str,
    args: List[str],
    timeout_s: int = 600,
) -> RunResult:
    """Execute PrusaSlicer with *args* and return the :class:`RunResult`.

    Parameters
    ----------
    exe:       Path to the PrusaSlicer executable.
    args:      Additional arguments (do **not** include the executable itself).
    timeout_s: Maximum wall-clock time (seconds) before raising
               :class:`RuntimeError`.

    Raises
    ------
    RuntimeError
        On timeout or if the executable cannot be launched.
    """
    cmd = [exe] + args
    try:
        r = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=timeout_s,
        )
        return RunResult(cmd=cmd, returncode=r.returncode, stdout=r.stdout, stderr=r.stderr)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"PrusaSlicer timed out after {timeout_s}s.  Command: {cmd!r}"
        )
    except OSError as exc:
        raise RuntimeError(f"Cannot run PrusaSlicer {exe!r}: {exc}") from exc


def slice_model(exe: str, req: SliceRequest) -> RunResult:
    """Slice a 3-D model with PrusaSlicer and write the G-code output.

    Builds the CLI command from *req* and delegates to
    :func:`run_prusaslicer`.

    Parameters
    ----------
    exe: Path to the PrusaSlicer executable.
    req: :class:`SliceRequest` describing the slicing job.

    Returns
    -------
    RunResult
        Exit code, stdout, and stderr from PrusaSlicer.
    """
    args: List[str] = []
    if req.config_ini:
        args += ["--load", req.config_ini]
    if req.printer_technology:
        args += ["--printer-technology", req.printer_technology]
    args += ["--export-gcode", "--output", req.output_path]
    args += req.extra_args
    args.append(req.input_path)
    return run_prusaslicer(exe, args)


def slice_batch(
    exe: str,
    inputs: List[str],
    output_dir: str,
    config_ini: Optional[str],
    naming: str = "{stem}.gcode",
    parallelism: int = 1,
) -> List[RunResult]:
    """Slice multiple models, writing output files to *output_dir*.

    Parameters
    ----------
    exe:         Path to the PrusaSlicer executable.
    inputs:      List of input model paths.
    output_dir:  Directory for output ``.gcode`` files (created if absent).
    config_ini:  Path to a PrusaSlicer ``.ini`` config (or ``None``).
    naming:      Output filename template.  ``{stem}`` is replaced with the
                 input file stem (filename without extension).
    parallelism: Number of concurrent PrusaSlicer processes (1 = serial).

    Returns
    -------
    List[RunResult]
        One :class:`RunResult` per input, in the same order as *inputs*.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def _do_one(inp: str) -> RunResult:
        stem = Path(inp).stem
        out_name = _render_template(naming, {"stem": stem})
        req = SliceRequest(
            input_path=inp,
            output_path=str(out_dir / out_name),
            config_ini=config_ini,
        )
        return slice_model(exe, req)

    if parallelism <= 1:
        return [_do_one(inp) for inp in inputs]

    with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as pool:
        futures = [pool.submit(_do_one, inp) for inp in inputs]
        return [f.result() for f in futures]


# ===========================================================================
# PrusaSlicer INI parsing
# ===========================================================================


def _ini_first_value(raw: str) -> str:
    """Return the first semicolon-delimited value from *raw*.

    PrusaSlicer uses semicolons to separate per-extruder values
    (e.g. ``"0.4;0.4"`` for dual-extruder nozzle_diameter).
    """
    return raw.split(";")[0].strip()


def _ini_parse_float(raw: str) -> Optional[float]:
    """Parse a float from the first semicolon-delimited value.

    Returns ``None`` on failure.
    """
    try:
        return float(_ini_first_value(raw))
    except (ValueError, IndexError):
        return None


def _ini_parse_int(raw: str) -> Optional[int]:
    """Parse an int (truncating any decimal part) from the first value.

    Returns ``None`` on failure.
    """
    f = _ini_parse_float(raw)
    return int(f) if f is not None else None


def _ini_parse_extrusion_width(raw: str) -> Optional[float]:
    """Parse extrusion width, which may be ``"0"`` (auto), a percentage, or mm.

    Returns a positive float in mm, or ``None`` when the value is auto,
    a percentage string, or otherwise unparseable.
    """
    val = _ini_first_value(raw)
    if val == "0" or val == "":
        return None  # auto
    if val.endswith("%"):
        return None  # percentage-based; not convertible without nozzle size
    try:
        result = float(val)
        return result if result > 0 else None
    except ValueError:
        return None


def _ini_parse_bed_shape(raw: str) -> Optional[str]:
    """Parse PrusaSlicer ``bed_shape`` and compute the bed centre.

    The expected format is ``"0x0,250x0,250x220,0x220"`` -- four corners
    of a rectangle with ``x`` as coordinate separator within each
    corner.  Returns the centre as ``"X,Y"`` (integer coordinates), or
    ``None`` when the value is malformed.
    """
    try:
        corners = raw.split(",")
        xs: List[float] = []
        ys: List[float] = []
        for corner in corners:
            parts = corner.strip().split("x")
            xs.append(float(parts[0]))
            ys.append(float(parts[1]))
        cx = int((min(xs) + max(xs)) / 2)
        cy = int((min(ys) + max(ys)) / 2)
        return f"{cx},{cy}"
    except (ValueError, IndexError):
        return None


def parse_prusaslicer_ini(path: str) -> Dict[str, Any]:
    """Parse a PrusaSlicer ``.ini`` file and extract slicer settings.

    The returned dict may contain any subset of these keys:

    - ``nozzle_diameter`` (float): Nozzle diameter in mm.
    - ``nozzle_temp`` (int): Nozzle temperature in deg-C.
    - ``bed_temp`` (int): Bed temperature in deg-C.
    - ``fan_speed`` (int): Fan speed 0-100%.
    - ``layer_height`` (float): Layer height in mm.
    - ``extrusion_width`` (float): Extrusion width in mm (only if explicit).
    - ``bed_center`` (str): Bed centre as ``"X,Y"`` (computed from
      ``bed_shape``).
    - ``printer_model`` (str): Printer model identifier.
    - ``filament_type`` (str): Filament type (e.g. ``"PETG"``, ``"PLA"``).

    Keys are omitted when the ``.ini`` file does not contain the relevant
    setting or the value cannot be parsed.

    Parameters
    ----------
    path : str
        Path to the PrusaSlicer ``.ini`` config file.

    Returns
    -------
    dict
        Extracted settings.  Empty dict if the file cannot be read.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")

    # PrusaSlicer config exports may lack section headers.
    # configparser requires at least one section, so prepend a default.
    if not any(line.strip().startswith("[") for line in text.splitlines()):
        text = "[DEFAULT]\n" + text

    parser = configparser.RawConfigParser()
    parser.read_string(text)

    # Collect all key-value pairs across all sections into a flat dict.
    # Start with DEFAULT, then let section-specific keys override.
    # parser.items(section) includes DEFAULT-inherited keys, so we only
    # accept keys explicitly set in the section (present in _sections),
    # not keys merely inherited from DEFAULT.
    defaults = parser.defaults()
    flat: Dict[str, str] = dict(defaults)
    for section in parser.sections():
        for key, value in parser.items(section):
            if key not in defaults or key in parser._sections[section]:
                flat[key] = value

    result: Dict[str, Any] = {}

    # --- Nozzle diameter ---
    if "nozzle_diameter" in flat:
        val = _ini_parse_float(flat["nozzle_diameter"])
        if val is not None and val > 0:
            result["nozzle_diameter"] = val

    # --- Nozzle temperature (prefer 'temperature' over fallback) ---
    for key in ("temperature", "first_layer_temperature"):
        if key in flat:
            val_i = _ini_parse_int(flat[key])
            if val_i is not None and val_i > 0:
                result["nozzle_temp"] = val_i
                break

    # --- Bed temperature ---
    for key in ("bed_temperature", "first_layer_bed_temperature"):
        if key in flat:
            val_i = _ini_parse_int(flat[key])
            if val_i is not None and val_i >= 0:
                result["bed_temp"] = val_i
                break

    # --- Fan speed ---
    if "max_fan_speed" in flat:
        val_i = _ini_parse_int(flat["max_fan_speed"])
        if val_i is not None and 0 <= val_i <= 100:
            result["fan_speed"] = val_i

    # --- Layer height ---
    if "layer_height" in flat:
        val = _ini_parse_float(flat["layer_height"])
        if val is not None and val > 0:
            result["layer_height"] = val

    # --- Extrusion width ---
    if "extrusion_width" in flat:
        val = _ini_parse_extrusion_width(flat["extrusion_width"])
        if val is not None:
            result["extrusion_width"] = val

    # --- Bed shape -> bed centre ---
    if "bed_shape" in flat:
        centre = _ini_parse_bed_shape(flat["bed_shape"])
        if centre is not None:
            result["bed_center"] = centre

    # --- Printer model ---
    if "printer_model" in flat:
        val_s = flat["printer_model"].strip()
        if val_s:
            result["printer_model"] = val_s

    # --- Filament type ---
    if "filament_type" in flat:
        val_s = _ini_first_value(flat["filament_type"]).strip()
        if val_s:
            result["filament_type"] = val_s

    return result


# ===========================================================================
# PrusaSlicer INI editing
# ===========================================================================


_PA_LINE_RE = re.compile(
    r"(M572\s+S[\d.]+|M900\s+K[\d.]+)",
    re.IGNORECASE,
)


def replace_ini_value(
    lines: List[str],
    key: str,
    new_value: str,
) -> Tuple[List[str], bool]:
    """Replace the first occurrence of *key* ``= ...`` with *new_value*.

    Returns ``(updated_lines, found)``.  Only the **first** matching line
    is replaced; subsequent duplicates are left untouched.  The
    whitespace around ``=`` is preserved from the original line.
    """
    pattern = re.compile(
        rf"^(\s*{re.escape(key)}\s*=\s*)(.*)$",
    )
    found = False
    result: List[str] = []
    for line in lines:
        if not found:
            m = pattern.match(line)
            if m:
                line_ending = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
                result.append(f"{m.group(1)}{new_value}{line_ending}")
                found = True
                continue
        result.append(line)
    return result, found


def pa_command(pa_value: float, printer: str = "COREONE") -> str:
    """Return the G-code command string for setting pressure advance.

    The Prusa Mini uses Linear Advance (``M900 K``).  All other
    Prusa printers use Pressure Advance (``M572 S``).
    """
    if printer.upper() == "MINI":
        return f"M900 K{pa_value:.4f}"
    return f"M572 S{pa_value:.4f}"


def inject_pa_into_start_gcode(
    lines: List[str],
    pa_value: float,
    printer: str = "COREONE",
) -> List[str]:
    r"""Insert or replace a PA command inside ``start_filament_gcode``.

    PrusaSlicer stores multi-line G-code values on a single INI line
    using literal ``\n`` escape sequences, e.g.::

        start_filament_gcode = "M572 S0.04\nG92 E0"

    This function finds the ``start_filament_gcode`` key, then either
    replaces an existing PA command within the value or prepends one.
    If the key is absent the line is appended at the end.
    """
    pa_cmd = pa_command(pa_value, printer)
    key_re = re.compile(r"^(\s*start_filament_gcode\s*=\s*)(.*)$")

    result: List[str] = []
    found = False

    for line in lines:
        if not found:
            m = key_re.match(line)
            if m:
                found = True
                prefix = m.group(1)
                raw_value = m.group(2)
                # Unquote if surrounded by quotes.
                stripped = raw_value.strip()
                if (
                    len(stripped) >= 2
                    and stripped[0] == '"'
                    and stripped[-1] == '"'
                ):
                    inner = stripped[1:-1]
                    quote = True
                else:
                    inner = stripped
                    quote = False

                if _PA_LINE_RE.search(inner):
                    # Replace existing PA command.
                    inner = _PA_LINE_RE.sub(pa_cmd, inner, count=1)
                elif inner:
                    # Prepend PA command before existing content.
                    inner = pa_cmd + "\\n" + inner
                else:
                    inner = pa_cmd

                if quote:
                    result.append(f'{prefix}"{inner}"')
                else:
                    result.append(f"{prefix}{inner}")
                continue
        result.append(line)

    if not found:
        result.append(f"start_filament_gcode = {pa_cmd}")

    return result
