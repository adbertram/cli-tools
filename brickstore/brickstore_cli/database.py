"""Read and refresh the local BrickStore BrickLink catalog database.

The file format is BrickStore's own chunked binary format, documented in
``src/utility/chunkreader.cpp`` and ``src/bricklink/database.cpp`` of
https://github.com/rgriebl/brickstore.

Every chunk is stored as::

    id (4 bytes) + version (uint32) + size (uint64)
    payload (size bytes)
    zero padding up to a multiple of 16
    size (uint64) + version (uint32) + id (4 bytes)

The whole file is one ``BSDB`` root chunk. All integers are little-endian.
BrickStore writes its ``QDataStream`` with double floating point precision, so
every C++ ``float`` field occupies 8 bytes on disk.
"""

import datetime
import hashlib
import lzma
import os
import struct
from pathlib import Path

import requests
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.exceptions import ClientError


MAGIC = b"BSDB"
SUPPORTED_VERSION = 12
DATABASE_FILE_NAME = "database-v{}".format(SUPPORTED_VERSION)
COMPRESSED_FILE_NAME = "{}.lzma".format(DATABASE_FILE_NAME)
ETAG_FILE_SUFFIX = ".etag"

CHUNK_HEADER_SIZE = 16
CHUNK_ALIGNMENT = 16
REQUIRED_CHUNKS = ("DATE", "COL ", "CAT ", "TYPE", "ITEM")

PART_TYPE_ID = "P"
SET_TYPE_ID = "S"
MINIFIG_TYPE_ID = "M"
INDEXED_TYPE_IDS = (SET_TYPE_ID, MINIFIG_TYPE_ID)
ITEM_TYPE_NAMES = {
    "B": "BOOK",
    "C": "CATALOG",
    "G": "GEAR",
    "I": "INSTRUCTION",
    "M": "MINIFIG",
    "O": "ORIGINAL_BOX",
    "P": "PART",
    "S": "SET",
    "U": "UNSORTED_LOT",
}

# A serialized QColor is a signed spec byte plus five quint16 channels.
QCOLOR_SIZE = 11
# Colour fields after the id and the name: LDraw id, colour, type flags,
# popularity, year range, LDraw colour, LDraw edge colour, luminance, particle
# sizes, particle colour, and the two particle fractions.
COLOR_TAIL_SIZE = 4 + QCOLOR_SIZE + 4 + 8 + 2 + 2 + QCOLOR_SIZE + QCOLOR_SIZE + 8 + 8 + 8 + QCOLOR_SIZE + 8 + 8
# Category fields after the id and the name: year from, year to, year recency,
# and the inventory flag.
CATEGORY_TAIL_SIZE = 4
# Item fields between the type indexes and the first array: year from, year to,
# and the weight double.
ITEM_SCALAR_TAIL_SIZE = 1 + 1 + 8

APPEARS_IN_RECORD_SIZE = 4
CONSISTS_OF_RECORD_SIZE = 8
DIMENSIONS_RECORD_SIZE = 8
PCC_RECORD_SIZE = 8
INDEX_RECORD_SIZE = 2

EMPTY_ARRAY_MARKER = 0xFFFFFFFF
JULIAN_DAY_OFFSET = 1721425
TIME_SPEC_LOCAL = 0
TIME_SPEC_UTC = 1

SHA512_HEADER_SIZE = 64
DOWNLOAD_TIMEOUT_SECONDS = 300
NOT_MODIFIED_STATUS = 304

_UINT16 = struct.Struct("<H")
_UINT32 = struct.Struct("<I")
_UINT64 = struct.Struct("<Q")
_QDATETIME = struct.Struct("<qIB")

activity = get_activity_logger("brickstore")


def _resolve(path) -> Path:
    """Return the expanded absolute database path."""
    return Path(path).expanduser()


def _etag_path(path: Path) -> Path:
    """Return the sidecar path that holds the download etag."""
    return path.with_name(path.name + ETAG_FILE_SUFFIX)


class _Cursor:
    """Walk a little-endian BrickStore record stream."""

    __slots__ = ("data", "offset")

    def __init__(self, data: bytes, offset: int):
        self.data = data
        self.offset = offset

    def uint8(self) -> int:
        value = self.data[self.offset]
        self.offset += 1
        return value

    def uint16(self) -> int:
        value = _UINT16.unpack_from(self.data, self.offset)[0]
        self.offset += 2
        return value

    def uint32(self) -> int:
        value = _UINT32.unpack_from(self.data, self.offset)[0]
        self.offset += 4
        return value

    def skip(self, count: int) -> None:
        self.offset += count

    def byte_array(self) -> bytes:
        """Read a PooledArray<char8_t>: a byte count then raw bytes."""
        size = self.uint32()
        if size == EMPTY_ARRAY_MARKER:
            return b""
        value = self.data[self.offset:self.offset + size]
        self.offset += size
        return value

    def text(self) -> str:
        """Read a PooledArray<char16_t>: a byte count then UTF-16 data."""
        size = self.uint32()
        if size == EMPTY_ARRAY_MARKER:
            return ""
        value = self.data[self.offset:self.offset + size].decode("utf-16-le")
        self.offset += size
        return value

    def array(self, record_size: int) -> tuple:
        """Read a PooledArray of fixed-size records and return (offset, count)."""
        count = self.uint32()
        if count == EMPTY_ARRAY_MARKER:
            return self.offset, 0
        start = self.offset
        self.offset += count * record_size
        return start, count


def _read_chunk(data: bytes, offset: int, path: Path) -> tuple:
    """Return (chunk_id, version, payload_offset, size, next_offset) for one chunk."""
    if offset + CHUNK_HEADER_SIZE > len(data):
        raise ClientError(
            "BrickStore database {} is truncated: a chunk header at byte {} runs past the end".format(path, offset)
        )
    chunk_id = data[offset:offset + 4].decode("latin-1")
    version = _UINT32.unpack_from(data, offset + 4)[0]
    size = _UINT64.unpack_from(data, offset + 8)[0]
    payload = offset + CHUNK_HEADER_SIZE
    footer = payload + size + (-size % CHUNK_ALIGNMENT)
    if footer + CHUNK_HEADER_SIZE > len(data):
        raise ClientError(
            "BrickStore database {} is truncated: chunk {} at byte {} runs past the end".format(
                path, chunk_id.strip(), offset
            )
        )
    footer_size = _UINT64.unpack_from(data, footer)[0]
    footer_version = _UINT32.unpack_from(data, footer + 8)[0]
    footer_id = data[footer + 12:footer + 16].decode("latin-1")
    if (footer_id, footer_version, footer_size) != (chunk_id, version, size):
        raise ClientError(
            "BrickStore database {} is corrupt: the footer of chunk {} at byte {} does not match its header".format(
                path, chunk_id.strip(), offset
            )
        )
    return chunk_id, version, payload, size, footer + CHUNK_HEADER_SIZE


def _index_chunks(data: bytes, path: Path) -> dict:
    """Validate the root chunk and return {chunk_id: (payload_offset, size)}."""
    if len(data) < CHUNK_HEADER_SIZE:
        raise ClientError("BrickStore database {} is truncated: the file is smaller than one chunk header".format(path))
    if data[:4] != MAGIC:
        raise ClientError(
            "BrickStore database {} is not a BrickStore database: expected the magic bytes {}".format(
                path, MAGIC.decode("ascii")
            )
        )
    version = _UINT32.unpack_from(data, 4)[0]
    if version != SUPPORTED_VERSION:
        raise ClientError(
            "BrickStore database {} has version {}, but this CLI reads version {}".format(
                path, version, SUPPORTED_VERSION
            )
        )

    _, _, payload, size, next_offset = _read_chunk(data, 0, path)
    if next_offset != len(data):
        raise ClientError(
            "BrickStore database {} is corrupt: {} bytes follow the root chunk".format(path, len(data) - next_offset)
        )

    chunks = {}
    offset = payload
    end = payload + size
    while offset < end:
        chunk_id, _, chunk_payload, chunk_size, offset = _read_chunk(data, offset, path)
        chunks[chunk_id] = (chunk_payload, chunk_size)
    if offset != end:
        raise ClientError("BrickStore database {} is corrupt: a chunk crosses the root chunk end".format(path))

    missing = [chunk_id for chunk_id in REQUIRED_CHUNKS if chunk_id not in chunks]
    if missing:
        raise ClientError(
            "BrickStore database {} is missing the required chunk(s) {}".format(
                path, ", ".join(chunk_id.strip() for chunk_id in missing)
            )
        )
    return chunks


def _require_exact_size(cursor: _Cursor, payload: int, size: int, chunk_id: str, path: Path) -> None:
    """Fail when a chunk parse did not consume exactly the declared payload."""
    if cursor.offset - payload != size:
        raise ClientError(
            "BrickStore database {} is corrupt: chunk {} declared {} bytes but parsed {}".format(
                path, chunk_id.strip(), size, cursor.offset - payload
            )
        )


class CatalogDatabase:
    """Expose BrickStore's local catalog database as plain records."""

    def __init__(self, path: Path, data: bytes, chunks: dict):
        self.path = path
        self._data = data
        self._generated_at = self._read_generation_date(chunks["DATE"])
        self._color_ids = self._read_colors(chunks["COL "])
        self._category_ids = self._read_categories(chunks["CAT "])
        self._type_ids = self._read_item_types(chunks["TYPE"])
        self._read_items(chunks["ITEM"])

    @classmethod
    def load(cls, path) -> "CatalogDatabase":
        """Read and validate the database file at the given path."""
        resolved = _resolve(path)
        if not resolved.is_file():
            raise ClientError(
                "BrickStore database {} does not exist. Run `brickstore database update` to download it, "
                "or set BRICKSTORE_DATABASE_PATH to the correct location.".format(resolved)
            )
        try:
            data = resolved.read_bytes()
        except OSError as error:
            raise ClientError("BrickStore database {} could not be read: {}".format(resolved, error)) from error
        activity.info("read %s (%s bytes)", resolved, len(data))
        return cls(resolved, data, _index_chunks(data, resolved))

    def _read_generation_date(self, chunk: tuple) -> datetime.datetime:
        payload, size = chunk
        if size < _QDATETIME.size:
            raise ClientError("BrickStore database {} is corrupt: the DATE chunk is too small".format(self.path))
        julian_day, milliseconds, time_spec = _QDATETIME.unpack_from(self._data, payload)
        if time_spec not in (TIME_SPEC_LOCAL, TIME_SPEC_UTC):
            raise ClientError(
                "BrickStore database {} is corrupt: the DATE chunk uses time spec {}".format(self.path, time_spec)
            )
        day = datetime.date.fromordinal(julian_day - JULIAN_DAY_OFFSET)
        stamp = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(milliseconds=milliseconds)
        if time_spec == TIME_SPEC_UTC:
            return stamp.replace(tzinfo=datetime.timezone.utc)
        return stamp

    def _read_indexed_ids(self, chunk: tuple, tail_size: int, chunk_id: str) -> list:
        payload, size = chunk
        cursor = _Cursor(self._data, payload)
        ids = []
        for _ in range(cursor.uint32()):
            ids.append(cursor.uint32())
            cursor.text()
            cursor.skip(tail_size)
        _require_exact_size(cursor, payload, size, chunk_id, self.path)
        return ids

    def _read_colors(self, chunk: tuple) -> list:
        return self._read_indexed_ids(chunk, COLOR_TAIL_SIZE, "COL ")

    def _read_categories(self, chunk: tuple) -> list:
        return self._read_indexed_ids(chunk, CATEGORY_TAIL_SIZE, "CAT ")

    def _read_item_types(self, chunk: tuple) -> list:
        payload, size = chunk
        cursor = _Cursor(self._data, payload)
        type_ids = []
        for _ in range(cursor.uint32()):
            type_ids.append(chr(cursor.uint8()))
            cursor.text()
            cursor.skip(1)
            cursor.array(INDEX_RECORD_SIZE)
        _require_exact_size(cursor, payload, size, "TYPE", self.path)
        return type_ids

    def _read_items(self, chunk: tuple) -> None:
        payload, size = chunk
        cursor = _Cursor(self._data, payload)
        count = cursor.uint32()
        self._item_ids = ids = [""] * count
        self._item_names = names = [""] * count
        self._item_type_names = type_names = [""] * count
        self._item_category_ids = category_ids = [None] * count
        self._consists_offsets = consists_offsets = [0] * count
        self._consists_counts = consists_counts = [0] * count
        self._indexes_by_type = {type_id: {} for type_id in INDEXED_TYPE_IDS}
        indexes_by_type_name = {
            ITEM_TYPE_NAMES[type_id]: self._indexes_by_type[type_id] for type_id in INDEXED_TYPE_IDS
        }

        for index in range(count):
            ids[index] = cursor.byte_array().decode("latin-1")
            names[index] = cursor.text()
            type_index = cursor.uint16()
            cursor.skip(2 + ITEM_SCALAR_TAIL_SIZE)
            type_names[index] = self._type_name(type_index)
            cursor.array(APPEARS_IN_RECORD_SIZE)
            consists_offsets[index], consists_counts[index] = cursor.array(CONSISTS_OF_RECORD_SIZE)
            cursor.array(INDEX_RECORD_SIZE)
            category_offset, category_count = cursor.array(INDEX_RECORD_SIZE)
            if category_count:
                category_ids[index] = self._category_ids[_UINT16.unpack_from(self._data, category_offset)[0]]
            cursor.array(INDEX_RECORD_SIZE)
            cursor.array(DIMENSIONS_RECORD_SIZE)
            cursor.array(PCC_RECORD_SIZE)
            cursor.byte_array()
            indexes = indexes_by_type_name.get(type_names[index])
            if indexes is not None:
                indexes[ids[index]] = index

        _require_exact_size(cursor, payload, size, "ITEM", self.path)

    def _type_name(self, type_index: int) -> str:
        if type_index >= len(self._type_ids):
            raise ClientError(
                "BrickStore database {} is corrupt: item type index {} is out of range".format(self.path, type_index)
            )
        type_id = self._type_ids[type_index]
        if type_id not in ITEM_TYPE_NAMES:
            raise ClientError(
                "BrickStore database {} holds the unknown item type {}".format(self.path, type_id)
            )
        return ITEM_TYPE_NAMES[type_id]

    def _contents_items(self, type_id: str, item_number: str) -> list:
        """Return the merged direct item records of one catalog item.

        BrickStore stores one record per BrickLink inventory row. BrickLink's
        own subsets response merges the regular row and the extra row of the
        same part into one entry, where ``quantity`` counts every unit and
        ``extra_quantity`` counts the extra units only. This method applies the
        same merge.
        """
        if not self.has_item(type_id, item_number):
            raise ClientError(
                "BrickStore database {} holds no {} with the ID {}".format(
                    self.path, ITEM_TYPE_NAMES[type_id].lower(), item_number
                )
            )
        index = self._indexes_by_type[type_id][item_number]
        offset = self._consists_offsets[index]
        entries = {}
        items = []
        for record in range(self._consists_counts[index]):
            value = _UINT64.unpack_from(self._data, offset + record * CONSISTS_OF_RECORD_SIZE)[0]
            quantity = value & 0xFFF
            item_index = (value >> 12) & 0xFFFFF
            color_index = (value >> 32) & 0xFFF
            is_extra = bool((value >> 44) & 1)
            is_alternate = bool((value >> 45) & 1)
            match_no = (value >> 46) & 0x3F
            is_counterpart = bool((value >> 52) & 1)
            key = (item_index, color_index, is_alternate, is_counterpart, match_no)
            entry = entries.get(key)
            if entry is None:
                entry = entries[key] = {
                    "item": {
                        "no": self._item_ids[item_index],
                        "name": self._item_names[item_index],
                        "type": self._item_type_names[item_index],
                        "category_id": self._item_category_ids[item_index],
                    },
                    "color_id": self._color_ids[color_index],
                    "quantity": 0,
                    "extra_quantity": 0,
                    "is_alternate": is_alternate,
                    "is_counterpart": is_counterpart,
                    "match_no": match_no,
                }
                items.append(entry)
            entry["quantity"] += quantity
            if is_extra:
                entry["extra_quantity"] += quantity
        return items

    def has_item(self, type_id: str, item_number: str) -> bool:
        """Return whether the catalog holds an item of the given indexed type."""
        return item_number in self._indexes_by_type[type_id]

    def contents(self, type_id: str, item_number: str) -> dict:
        """Return the direct item records of one catalog item, keyed by its type noun."""
        noun = ITEM_TYPE_NAMES[type_id].lower()
        return {"{}_id".format(noun): item_number, "items": self._contents_items(type_id, item_number)}

    def status(self) -> dict:
        """Return the loaded database metadata."""
        status = {
            "path": str(self.path),
            "version": SUPPORTED_VERSION,
            "generated_at": self._generated_at.isoformat(),
            "etag": read_etag(self.path),
            "colors": len(self._color_ids),
            "categories": len(self._category_ids),
            "item_types": len(self._type_ids),
            "items": len(self._item_ids),
        }
        for type_id in INDEXED_TYPE_IDS:
            indexes = self._indexes_by_type[type_id]
            noun = "{}s".format(ITEM_TYPE_NAMES[type_id].lower())
            status[noun] = len(indexes)
            status["{}_with_inventory".format(noun)] = sum(
                1 for index in indexes.values() if self._consists_counts[index]
            )
        return status


def read_etag(path) -> str | None:
    """Return the stored download etag, or None when no sidecar file exists."""
    sidecar = _etag_path(_resolve(path))
    if not sidecar.is_file():
        return None
    return sidecar.read_text(encoding="utf-8").strip()


def _download_url(url: str) -> str:
    """Return the full URL of the compressed database."""
    return "{}/{}".format(url.rstrip("/"), COMPRESSED_FILE_NAME)


def _decompress(body: bytes, source: str) -> bytes:
    """Verify the SHA-512 header and return the plain database bytes."""
    if len(body) <= SHA512_HEADER_SIZE:
        raise ClientError("BrickStore database download from {} is too small to be valid".format(source))
    digest = body[:SHA512_HEADER_SIZE]
    try:
        plain = lzma.decompress(body[SHA512_HEADER_SIZE:], format=lzma.FORMAT_ALONE)
    except lzma.LZMAError as error:
        raise ClientError("BrickStore database download from {} is not valid LZMA: {}".format(source, error)) from error
    if hashlib.sha512(plain).digest() != digest:
        raise ClientError("BrickStore database download from {} failed its SHA-512 check".format(source))
    if plain[:4] != MAGIC:
        raise ClientError("BrickStore database download from {} has the wrong magic bytes".format(source))
    version = _UINT32.unpack_from(plain, 4)[0]
    if version != SUPPORTED_VERSION:
        raise ClientError(
            "BrickStore database download from {} has version {}, but this CLI reads version {}".format(
                source, version, SUPPORTED_VERSION
            )
        )
    return plain


def download(path, url: str, force: bool = False) -> dict:
    """Download the newest database and install it at the given path.

    The download is a plain HTTPS GET of BrickStore's own published database.
    It makes no BrickLink API call. The new file replaces the old one only
    after the SHA-512 header, the LZMA stream, and the magic bytes all pass.
    """
    resolved = _resolve(path)
    source = _download_url(url)
    headers = {}
    current_etag = read_etag(resolved)
    if not force and current_etag is not None and resolved.is_file():
        headers["If-None-Match"] = current_etag

    try:
        response = requests.get(source, headers=headers, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as error:
        raise ClientError("BrickStore database download from {} failed: {}".format(source, error)) from error
    activity.info("GET %s -> %s", source, response.status_code)

    if response.status_code == NOT_MODIFIED_STATUS:
        return {"path": str(resolved), "url": url, "updated": False, "etag": current_etag}
    if response.status_code != 200:
        raise ClientError(
            "BrickStore database server returned HTTP {} for {}".format(response.status_code, source)
        )
    if "ETag" not in response.headers:
        raise ClientError("BrickStore database server returned no ETag for {}".format(source))

    plain = _decompress(response.content, source)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    staged = resolved.with_name(resolved.name + ".download")
    staged.write_bytes(plain)
    os.replace(staged, resolved)
    _etag_path(resolved).write_text(response.headers["ETag"], encoding="utf-8")
    return {
        "path": str(resolved),
        "url": url,
        "updated": True,
        "etag": response.headers["ETag"],
        "compressed_bytes": len(response.content),
        "bytes": len(plain),
    }
