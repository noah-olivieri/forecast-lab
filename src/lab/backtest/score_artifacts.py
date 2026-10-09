"""Immutable RF-001 records and prefix-sharing ordered histories (schema v2).

References are SHA-256 of canonical JSON without the file's final newline.
Readers verify every referenced object; no source files or network are needed.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from lab.backtest.score_data import Game, Label, Observation, Vintage, canonical, digest, utc


@lru_cache(maxsize=100000)
def record_ref(value):
    return f"records/{digest({'kind': type(value).__name__, 'value': value})}.json"


@lru_cache(maxsize=200000)
def sequence_node(previous, record, length):
    node = {"previous": previous, "record": record, "length": length}
    return f"sequences/{digest(node)}.json", node


def observation_root(observations):
    previous = None
    for length, value in enumerate(observations, 1):
        previous, _ = sequence_node(previous, record_ref(value), length)
    return previous


class RecordStore:
    def __init__(self, root):
        self.root = Path(root)
        self.written = set()

    def put(self, ref, value):
        if ref not in self.written:
            path = self.root / ref
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = canonical(value) + "\n"
            if path.exists():
                if path.read_text() != payload:
                    raise ValueError("immutable content hash collision / altered record")
            else:
                with path.open("x") as handle:
                    handle.write(payload)
            self.written.add(ref)
        return ref

    def observations(self, values):
        previous = None
        for length, value in enumerate(values, 1):
            ref = self.put(record_ref(value), {"kind": "Observation", "value": value})
            # Label records are shared with residual entries.
            self.put(record_ref(value.label), {"kind": "Label", "value": value.label})
            previous, node = sequence_node(previous, ref, length)
            self.put(previous, node)
        return previous

    def bank(self, values):
        previous = None
        for length, value in enumerate(values, 1):
            payload = {"kind": "Residual", "value": value}
            ref = self.put(f"records/{digest(payload)}.json", payload)
            previous, node = sequence_node(previous, ref, length)
            self.put(previous, node)
        descriptor = {"schema": "rf001-bank-v2", "root": previous, "n": len(values)}
        return self.put(f"banks/{digest(descriptor)}.json", descriptor)


def read_record(root, ref):
    if not re.fullmatch(r"(?:records|sequences|banks|fits)/[0-9a-f]{64}\.json", ref):
        raise ValueError("unsafe content reference")
    path = Path(root) / ref
    if path.is_symlink():
        raise ValueError("symlink content reference")
    value = json.loads(path.read_bytes())
    if digest(value) != Path(ref).stem:
        raise ValueError("content hash mismatch")
    return value


def read_sequence(root, ref):
    values, expected = [], None
    while ref is not None:
        node = read_record(root, ref)
        if expected is not None and node["length"] != expected:
            raise ValueError("invalid sequence length")
        expected = node["length"] - 1
        values.append(read_record(root, node["record"]))
        ref = node["previous"]
    if expected not in (None, 0):
        raise ValueError("incomplete sequence")
    return list(reversed(values))


def _vintage(value):
    return Vintage(
        **{k: utc(v) if k.endswith("_ts") and v is not None else v for k, v in value.items()}
    )


def read_observations(root, ref):
    observations = []
    for record in read_sequence(root, ref):
        if record["kind"] != "Observation":
            raise ValueError("observation record required")
        game, label = record["value"]["game"], record["value"]["label"]
        game = Game(**dict(game, kickoff=utc(game["kickoff"]), vintage=_vintage(game["vintage"])))
        label = Label(**dict(label, vintage=_vintage(label["vintage"])))
        observations.append(Observation(game, label))
    return observations


def read_bank(root, ref):
    descriptor = read_record(root, ref)
    bank = read_sequence(root, descriptor["root"])
    if len(bank) != descriptor["n"] or any(x["kind"] != "Residual" for x in bank):
        raise ValueError("invalid residual bank")
    return [x["value"] for x in bank]
