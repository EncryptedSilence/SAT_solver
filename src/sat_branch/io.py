"""JSON I/O for layer and SPN specifications."""
from __future__ import annotations

import json
from pathlib import Path

from .layer import LinearLayer
from .spn import Column, SPNSpec


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_layer(path: str | Path) -> LinearLayer:
    data = load_json(path)
    n = int(data["n"])
    if "matrix" in data:
        return LinearLayer.from_matrix(data["matrix"])
    if "operations" in data:
        return LinearLayer.from_operations(data["operations"], n)
    raise ValueError("input must have either 'matrix' or 'operations'")


def load_spn(path: str | Path) -> SPNSpec:
    data = load_json(path)
    if data.get("type") != "spn":
        raise ValueError("input JSON must have \"type\": \"spn\"")
    cols = []
    for c in data["columns"]:
        cols.append(Column(
            input_cells=list(c["input_cells"]),
            output_cells=list(c["output_cells"]),
            branch_number=int(c["branch_number"]),
        ))
    return SPNSpec(
        n_cells=int(data["n_cells"]),
        cell_bits=int(data.get("cell_bits", 8)),
        columns=cols,
    )
