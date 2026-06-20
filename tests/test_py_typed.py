"""Marker-distribution checks for PEP 561 typing support."""

from importlib.resources import files


def test_py_typed_marker_present():
    # PEP 561: the marker must sit at the package root for downstream type
    # checkers to treat promptpolygraph as typed.
    marker = files("promptpolygraph").joinpath("py.typed")
    assert marker.is_file()


def test_py_typed_marker_is_empty():
    # An informational py.typed marker is conventionally empty; a non-empty
    # file would be parsed as a partial-stub package listing.
    marker = files("promptpolygraph").joinpath("py.typed")
    assert marker.read_text() == ""
