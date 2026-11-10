"""COM backend infrastructure and business mixins.

S2:
- _constants / _helpers / probe / sta / infrastructure split out
- backend.ComBackend is the new composite (not yet default)
- com_backend.ComBackend is the legacy implementation (retained)

After S6: switch the default to com.backend.ComBackend.
"""
from cadmcp.backend.solidworks.backend import ComBackend
from cadmcp.backend.solidworks.probe import Win32DialogProbe

__all__ = ["ComBackend", "Win32DialogProbe"]
