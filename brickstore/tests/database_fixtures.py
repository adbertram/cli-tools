"""Byte-level builder for BrickStore's BSDB catalog database format.

Mirrors the encoding that brickstore_cli/database.py parses, so tests can
exercise the real parser against real bytes instead of mocks.
"""

import datetime
import struct


MAGIC = b"BSDB"
VERSION = 12
JULIAN_DAY_OFFSET = 1721425
TIME_SPEC_UTC = 1

_UINT16 = struct.Struct("<H")
_UINT32 = struct.Struct("<I")
_UINT64 = struct.Struct("<Q")
_QDATETIME = struct.Struct("<qIB")

COLOR_TAIL_SIZE = 104
CATEGORY_TAIL_SIZE = 4
ITEM_SCALAR_SKIP_SIZE = 12


def _pack_byte_array(data: bytes) -> bytes:
    return _UINT32.pack(len(data)) + data


def _pack_text(value: str) -> bytes:
    encoded = value.encode("utf-16-le")
    return _UINT32.pack(len(encoded)) + encoded


def _pack_array(records: list) -> bytes:
    return _UINT32.pack(len(records)) + b"".join(records)


def build_chunk(chunk_id: bytes, payload: bytes, version: int = VERSION) -> bytes:
    """Encode one length-prefixed, footer-verified BSDB chunk."""
    size = len(payload)
    pad = (-size) % 16
    header = chunk_id + _UINT32.pack(version) + _UINT64.pack(size)
    footer = _UINT64.pack(size) + _UINT32.pack(version) + chunk_id
    return header + payload + b"\x00" * pad + footer


def pack_consists_of(
    quantity: int,
    item_index: int,
    color_index: int,
    is_extra: bool = False,
    is_alternate: bool = False,
    match_no: int = 0,
    is_counterpart: bool = False,
) -> bytes:
    """Pack one bit-packed 'consists of' record, matching database.py's unpacking."""
    value = quantity & 0xFFF
    value |= (item_index & 0xFFFFF) << 12
    value |= (color_index & 0xFFF) << 32
    value |= (1 if is_extra else 0) << 44
    value |= (1 if is_alternate else 0) << 45
    value |= (match_no & 0x3F) << 46
    value |= (1 if is_counterpart else 0) << 52
    return _UINT64.pack(value)


def date_chunk(when: datetime.datetime) -> bytes:
    julian_day = when.date().toordinal() + JULIAN_DAY_OFFSET
    payload = _QDATETIME.pack(julian_day, 0, TIME_SPEC_UTC)
    return build_chunk(b"DATE", payload)


def colors_chunk(colors: list) -> bytes:
    """colors: list of (color_id, name)."""
    records = [_UINT32.pack(color_id) + _pack_text(name) + b"\x00" * COLOR_TAIL_SIZE for color_id, name in colors]
    return build_chunk(b"COL ", _pack_array(records))


def categories_chunk(categories: list) -> bytes:
    """categories: list of (category_id, name)."""
    records = [
        _UINT32.pack(category_id) + _pack_text(name) + b"\x00" * CATEGORY_TAIL_SIZE
        for category_id, name in categories
    ]
    return build_chunk(b"CAT ", _pack_array(records))


def item_types_chunk(item_types: list) -> bytes:
    """item_types: list of (single-letter type_id, name)."""
    records = [type_id.encode("latin-1") + _pack_text(name) + b"\x00" + _pack_array([]) for type_id, name in item_types]
    return build_chunk(b"TYPE", _pack_array(records))


def items_chunk(items: list) -> bytes:
    """items: list of dicts with no/name/type_index, optional category_index/consists_of."""
    records = []
    for item in items:
        category_index = item.get("category_index")
        category_records = [] if category_index is None else [_UINT16.pack(category_index)]
        record = b"".join(
            [
                _pack_byte_array(item["no"].encode("latin-1")),
                _pack_text(item["name"]),
                _UINT16.pack(item["type_index"]),
                b"\x00" * ITEM_SCALAR_SKIP_SIZE,
                _pack_array([]),  # appears_in
                _pack_array(item.get("consists_of", [])),
                _pack_array([]),  # unused index array
                _pack_array(category_records),
                _pack_array([]),  # unused index array
                _pack_array([]),  # dimensions
                _pack_array([]),  # price component candidates
                _pack_byte_array(b""),  # trailing byte blob
            ]
        )
        records.append(record)
    return build_chunk(b"ITEM", _pack_array(records))


def build_database(
    colors,
    categories,
    item_types,
    items,
    generated_at=None,
    chunks=("DATE", "COL ", "CAT ", "TYPE", "ITEM"),
) -> bytes:
    """Build a full BSDB file. `chunks` controls which top-level chunks are included."""
    generated_at = generated_at or datetime.datetime(2026, 1, 1)
    available = {
        "DATE": date_chunk(generated_at),
        "COL ": colors_chunk(colors),
        "CAT ": categories_chunk(categories),
        "TYPE": item_types_chunk(item_types),
        "ITEM": items_chunk(items),
    }
    payload = b"".join(available[chunk_id] for chunk_id in chunks)
    return build_chunk(MAGIC, payload)


def _contents_database(item_numbers, item_types, holder_type_id, holder_name, generated_at=None) -> bytes:
    """Build a database whose holder items contain 3 of one part (2 regular + 1 extra)."""
    holder_type_index = [type_id for type_id, _ in item_types].index(holder_type_id)
    items = [
        {"no": "3001", "name": "Brick 2 x 4", "type_index": 0, "category_index": 0},
    ]
    for item_number in item_numbers:
        items.append(
            {
                "no": item_number,
                "name": holder_name,
                "type_index": holder_type_index,
                "consists_of": [
                    pack_consists_of(quantity=2, item_index=0, color_index=0),
                    pack_consists_of(quantity=1, item_index=0, color_index=0, is_extra=True),
                ],
            }
        )
    return build_database(
        colors=[(5, "Red")],
        categories=[(5, "Basic")],
        item_types=item_types,
        items=items,
        generated_at=generated_at,
    )


def set_database(set_numbers, generated_at=None) -> bytes:
    """Build a database whose sets contain 3 of one part (2 regular + 1 extra)."""
    return _contents_database(
        set_numbers,
        item_types=[("P", "Part"), ("S", "Set")],
        holder_type_id="S",
        holder_name="Santa's Sleigh Ride polybag",
        generated_at=generated_at,
    )


def minifig_database(minifig_numbers, generated_at=None) -> bytes:
    """Build a database whose minifigs contain 3 of one part (2 regular + 1 extra)."""
    return _contents_database(
        minifig_numbers,
        item_types=[("P", "Part"), ("S", "Set"), ("M", "Minifig")],
        holder_type_id="M",
        holder_name="Luke Skywalker (Pilot)",
        generated_at=generated_at,
    )


def one_set_one_part_database(generated_at=None) -> bytes:
    """A minimal database with one set."""
    return set_database(["30670-1"], generated_at)


def two_sets_one_part_database(generated_at=None) -> bytes:
    """A minimal database with two sets."""
    return set_database(["30670-1", "75313-1"], generated_at)
