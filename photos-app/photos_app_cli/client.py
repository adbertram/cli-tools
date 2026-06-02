"""Photos library client using SQLite for queries and AppleScript for exports."""
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from .models import Photo, Album, AssetKind, CloudStatus


class ClientError(Exception):
    """Custom exception for Photos library errors."""
    pass


# Apple Core Data timestamp epoch (January 1, 2001)
APPLE_EPOCH = datetime(2001, 1, 1)

# Default Photos library location
DEFAULT_PHOTOS_LIBRARY = Path.home() / "Pictures/Photos Library.photoslibrary"


class PhotosClient:
    """Client for querying macOS Photos library.

    Uses SQLite for fast metadata queries and AppleScript for exports
    (which handles iCloud downloads automatically).
    """

    def __init__(self, library_path: Optional[Path] = None):
        """Initialize Photos library client.

        Args:
            library_path: Optional custom path to Photos library
        """
        self.library_path = library_path or DEFAULT_PHOTOS_LIBRARY
        self.db_path = self.library_path / "database/Photos.sqlite"

        if not self.db_path.exists():
            raise ClientError(
                f"Photos database not found at {self.db_path}. "
                "Make sure the Photos library exists."
            )

    def _apple_to_datetime(self, ts: Optional[float]) -> Optional[datetime]:
        """Convert Apple timestamp to Python datetime."""
        if ts is None:
            return None
        return APPLE_EPOCH + timedelta(seconds=ts)

    def _datetime_to_apple(self, dt: datetime) -> float:
        """Convert Python datetime to Apple timestamp."""
        return (dt - APPLE_EPOCH).total_seconds()

    def _connect(self) -> sqlite3.Connection:
        """Create a read-only database connection."""
        # Use URI mode for read-only access
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def is_available(self) -> bool:
        """Check if Photos library is accessible."""
        try:
            with self._connect() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM ZASSET")
                cursor.fetchone()
                return True
        except Exception:
            return False

    def list_albums(self, include_system: bool = False, exclude_folders: Optional[List[str]] = None) -> List[Album]:
        """List all albums in the library.

        Args:
            include_system: Include system albums (imports, sync, etc.)
            exclude_folders: Exclude albums inside these folder names

        Returns:
            List of Album models ordered by title
        """
        # ZKIND = 2 is user-created albums; higher values are system albums
        if include_system:
            kind_condition = "ZKIND >= 2"
        else:
            kind_condition = "ZKIND = 2"

        params: List = []
        exclude_clause = ""
        if exclude_folders:
            placeholders = ", ".join(["?" for _ in exclude_folders])
            exclude_clause = f"""
                AND ZPARENTFOLDER NOT IN (
                    SELECT Z_PK FROM ZGENERICALBUM
                    WHERE LOWER(ZTITLE) IN ({placeholders})
                )
            """
            params.extend([f.lower() for f in exclude_folders])

        query = f"""
            SELECT
                ZUUID,
                ZTITLE,
                ZCACHEDPHOTOSCOUNT,
                ZCACHEDVIDEOSCOUNT,
                ZCREATIONDATE
            FROM ZGENERICALBUM
            WHERE {kind_condition}
                AND ZTITLE IS NOT NULL
                AND ZTRASHEDSTATE = 0
                {exclude_clause}
            ORDER BY ZTITLE
        """

        albums = []
        with self._connect() as conn:
            cursor = conn.execute(query, params)
            for row in cursor:
                album = Album(
                    uuid=row["ZUUID"],
                    title=row["ZTITLE"],
                    photo_count=row["ZCACHEDPHOTOSCOUNT"] or 0,
                    video_count=row["ZCACHEDVIDEOSCOUNT"] or 0,
                    date_created=self._apple_to_datetime(row["ZCREATIONDATE"]),
                )
                albums.append(album)

        return albums

    def _get_album_pk(self, album_name: str) -> Optional[int]:
        """Get the primary key for an album by name.

        Args:
            album_name: Album title (case-insensitive)

        Returns:
            Album Z_PK or None if not found
        """
        query = """
            SELECT Z_PK FROM ZGENERICALBUM
            WHERE LOWER(TRIM(ZTITLE)) = LOWER(?)
                AND ZTRASHEDSTATE = 0
            LIMIT 1
        """
        with self._connect() as conn:
            cursor = conn.execute(query, (album_name,))
            row = cursor.fetchone()
            return row["Z_PK"] if row else None

    def list_photos(
        self,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100,
        include_hidden: bool = False,
        include_videos: bool = False,
        album: Optional[str] = None,
    ) -> List[Photo]:
        """Query photos from the library.

        Args:
            from_date: Filter photos created on or after this date
            to_date: Filter photos created on or before this date
            limit: Maximum number of photos to return
            include_hidden: Include hidden photos
            include_videos: Include videos (default photos only)
            album: Filter by album name (case-insensitive)

        Returns:
            List of Photo models ordered by date created (newest first)
        """
        # Build query
        conditions = ["a.ZTRASHEDSTATE = 0"]  # Not in trash

        if not include_hidden:
            conditions.append("a.ZHIDDEN = 0")

        if not include_videos:
            conditions.append("a.ZKIND = 0")  # Photos only

        params: List = []
        join_clause = ""

        if album:
            album_pk = self._get_album_pk(album)
            if album_pk is None:
                return []  # Album not found, return empty list
            join_clause = "INNER JOIN Z_30ASSETS j ON a.Z_PK = j.Z_3ASSETS"
            conditions.append("j.Z_30ALBUMS = ?")
            params.append(album_pk)

        if from_date:
            conditions.append("a.ZDATECREATED >= ?")
            params.append(self._datetime_to_apple(from_date))

        if to_date:
            # Add a day to include the entire end date
            to_date_end = to_date + timedelta(days=1)
            conditions.append("a.ZDATECREATED < ?")
            params.append(self._datetime_to_apple(to_date_end))

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT
                a.ZUUID,
                a.ZFILENAME,
                a.ZDATECREATED,
                a.ZADDEDDATE,
                a.ZKIND,
                a.ZUNIFORMTYPEIDENTIFIER,
                a.ZWIDTH,
                a.ZHEIGHT,
                a.ZCLOUDLOCALSTATE,
                a.ZFAVORITE,
                a.ZHIDDEN
            FROM ZASSET a
            {join_clause}
            WHERE {where_clause}
            ORDER BY a.ZDATECREATED DESC
            LIMIT ?
        """
        params.append(limit)

        photos = []
        with self._connect() as conn:
            cursor = conn.execute(query, params)
            for row in cursor:
                photo = Photo(
                    uuid=row["ZUUID"],
                    filename=row["ZFILENAME"],
                    date_created=self._apple_to_datetime(row["ZDATECREATED"]),
                    date_added=self._apple_to_datetime(row["ZADDEDDATE"]),
                    kind=AssetKind.VIDEO if row["ZKIND"] == 1 else AssetKind.PHOTO,
                    file_type=row["ZUNIFORMTYPEIDENTIFIER"],
                    width=row["ZWIDTH"],
                    height=row["ZHEIGHT"],
                    cloud_status=CloudStatus.LOCAL if row["ZCLOUDLOCALSTATE"] == 0 else CloudStatus.ICLOUD,
                    is_favorite=bool(row["ZFAVORITE"]),
                    is_hidden=bool(row["ZHIDDEN"]),
                )
                photos.append(photo)

        return photos

    def export_photos(
        self,
        uuids: List[str],
        destination: Path,
    ) -> List[Path]:
        """Export photos to destination folder using AppleScript.

        This method triggers Photos.app to export the photos, which
        automatically handles downloading from iCloud if needed.

        Args:
            uuids: List of photo UUIDs to export
            destination: Destination folder path

        Returns:
            List of exported file paths

        Raises:
            ClientError: If export fails
        """
        if not uuids:
            return []

        # Ensure destination exists
        destination = destination.expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)

        # Build AppleScript to export photos
        # We search by UUID prefix since AppleScript IDs have format "UUID/L0/001"
        uuid_conditions = " or ".join([f'id contains "{uuid}"' for uuid in uuids])

        script = f'''
            tell application "Photos"
                set theItems to (every media item whose {uuid_conditions})
                if (count of theItems) > 0 then
                    set destFolder to POSIX file "{destination}" as alias
                    export theItems to destFolder
                    set exportedFiles to {{}}
                    repeat with theItem in theItems
                        set end of exportedFiles to filename of theItem
                    end repeat
                    return exportedFiles
                else
                    return {{}}
                end if
            end tell
        '''

        # Get list of files before export to detect new files
        existing_files = set(destination.iterdir()) if destination.exists() else set()

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for downloads
            )

            if result.returncode != 0:
                raise ClientError(f"Export failed: {result.stderr.strip()}")

            # Check if export was successful
            output = result.stdout.strip()
            if not output or output == "{}":
                return []

            # Scan destination for actual exported files (more reliable than AppleScript output)
            # AppleScript returns metadata filenames which may differ from actual files
            current_files = set(destination.iterdir())
            new_files = current_files - existing_files

            # Filter to only image/video files
            image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp", ".mov", ".mp4"}
            exported = [f for f in new_files if f.suffix.lower() in image_extensions]

            return sorted(exported, key=lambda p: p.name)

        except subprocess.TimeoutExpired:
            raise ClientError("Export timed out - photos may still be downloading from iCloud")
        except Exception as e:
            if isinstance(e, ClientError):
                raise
            raise ClientError(f"Export failed: {e}")

    def get_photo_count(self) -> int:
        """Get total number of photos in the library."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM ZASSET WHERE ZKIND = 0 AND ZTRASHEDSTATE = 0 AND ZHIDDEN = 0"
            )
            return cursor.fetchone()[0]

    def create_album(self, name: str) -> Album:
        """Create a new album in the Photos library.

        Uses AppleScript to create the album via Photos.app.

        Args:
            name: Name for the new album

        Returns:
            The created Album model

        Raises:
            ClientError: If album creation fails or album already exists
        """
        # Check if album already exists
        existing = self._get_album_pk(name)
        if existing:
            raise ClientError(f"Album '{name}' already exists")

        script = f'''
            tell application "Photos"
                set newAlbum to make new album named "{name}"
                return id of newAlbum
            end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                raise ClientError(f"Failed to create album: {result.stderr.strip()}")

            # Fetch the created album from the database
            # Give Photos.app a moment to sync
            import time
            time.sleep(0.5)

            # Query for the album we just created
            query = """
                SELECT
                    ZUUID,
                    ZTITLE,
                    ZCACHEDPHOTOSCOUNT,
                    ZCACHEDVIDEOSCOUNT,
                    ZCREATIONDATE
                FROM ZGENERICALBUM
                WHERE LOWER(ZTITLE) = LOWER(?)
                    AND ZTRASHEDSTATE = 0
                ORDER BY ZCREATIONDATE DESC
                LIMIT 1
            """
            with self._connect() as conn:
                cursor = conn.execute(query, (name,))
                row = cursor.fetchone()
                if row:
                    return Album(
                        uuid=row["ZUUID"],
                        title=row["ZTITLE"],
                        photo_count=row["ZCACHEDPHOTOSCOUNT"] or 0,
                        video_count=row["ZCACHEDVIDEOSCOUNT"] or 0,
                        date_created=self._apple_to_datetime(row["ZCREATIONDATE"]),
                    )

            # If we can't find it in the database, return a minimal Album
            return Album(uuid="", title=name)

        except subprocess.TimeoutExpired:
            raise ClientError("Album creation timed out")
        except Exception as e:
            if isinstance(e, ClientError):
                raise
            raise ClientError(f"Failed to create album: {e}")

    def delete_album(self, name: str) -> bool:
        """Delete an album from the Photos library.

        Uses AppleScript to delete the album via Photos.app.
        Note: This only deletes the album, not the photos in it.

        Args:
            name: Name of the album to delete

        Returns:
            True if album was deleted

        Raises:
            ClientError: If album deletion fails or album not found
        """
        # Check if album exists
        existing = self._get_album_pk(name)
        if not existing:
            raise ClientError(f"Album '{name}' not found")

        # Escape quotes in album name for AppleScript
        escaped_name = name.replace('"', '\\"')

        script = f'''
            tell application "Photos"
                set targetAlbum to first album whose name is "{escaped_name}"
                delete targetAlbum
            end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                raise ClientError(f"Failed to delete album: {result.stderr.strip()}")

            return True

        except subprocess.TimeoutExpired:
            raise ClientError("Album deletion timed out")
        except Exception as e:
            if isinstance(e, ClientError):
                raise
            raise ClientError(f"Failed to delete album: {e}")

    def move_album_to_folder(self, album_name: str, folder_name: str) -> Album:
        """Move an album into a folder in the Photos library.

        macOS Photos doesn't support a direct move verb, so this:
        1. Gets all media items from the source album
        2. Creates a new album with the same name inside the target folder
           (auto-creates the folder if it doesn't exist)
        3. Adds media items to the new album
        4. Deletes the source album

        Args:
            album_name: Name of the album to move
            folder_name: Name of the target folder

        Returns:
            The moved Album model

        Raises:
            ClientError: If album not found or operation fails
        """
        # Validate source album exists
        existing = self._get_album_pk(album_name)
        if not existing:
            raise ClientError(f"Album '{album_name}' not found")

        # Escape quotes for AppleScript
        escaped_album = album_name.replace('"', '\\"')
        escaped_folder = folder_name.replace('"', '\\"')

        script = f'''
            tell application "Photos"
                set sourceAlbum to first album whose name is "{escaped_album}"
                set sourcePhotos to every media item of sourceAlbum
                try
                    set targetFolder to first folder whose name is "{escaped_folder}"
                on error
                    set targetFolder to make new folder named "{escaped_folder}"
                end try
                set newAlbum to make new album named "{escaped_album}" at targetFolder
                if (count of sourcePhotos) > 0 then
                    add sourcePhotos to newAlbum
                end if
                delete sourceAlbum
                return id of newAlbum
            end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                raise ClientError(f"Failed to move album: {result.stderr.strip()}")

            # Give Photos.app a moment to sync
            import time
            time.sleep(0.5)

            # Query for the moved album from the database
            query = """
                SELECT
                    ZUUID,
                    ZTITLE,
                    ZCACHEDPHOTOSCOUNT,
                    ZCACHEDVIDEOSCOUNT,
                    ZCREATIONDATE
                FROM ZGENERICALBUM
                WHERE LOWER(ZTITLE) = LOWER(?)
                    AND ZTRASHEDSTATE = 0
                ORDER BY ZCREATIONDATE DESC
                LIMIT 1
            """
            with self._connect() as conn:
                cursor = conn.execute(query, (album_name,))
                row = cursor.fetchone()
                if row:
                    return Album(
                        uuid=row["ZUUID"],
                        title=row["ZTITLE"],
                        photo_count=row["ZCACHEDPHOTOSCOUNT"] or 0,
                        video_count=row["ZCACHEDVIDEOSCOUNT"] or 0,
                        date_created=self._apple_to_datetime(row["ZCREATIONDATE"]),
                    )

            # If we can't find it in the database, return a minimal Album
            return Album(uuid="", title=album_name)

        except subprocess.TimeoutExpired:
            raise ClientError("Album move timed out")
        except Exception as e:
            if isinstance(e, ClientError):
                raise
            raise ClientError(f"Failed to move album: {e}")

    def auto_enhance_photo(self, uuid: str, delay: float = 1.5) -> bool:
        """Auto-enhance a single photo using Photos.app's built-in enhancement.

        Opens the photo in Photos.app and triggers auto-enhance via Cmd+E.
        Note: Auto-enhance is a toggle — running on an already-enhanced photo
        removes the enhancement.

        Args:
            uuid: Photo UUID to enhance
            delay: Seconds to wait between UI steps for rendering

        Returns:
            True on success

        Raises:
            ClientError: If enhancement fails or photo not found
        """
        script = f'''
            tell application "Photos"
                activate
                set theItems to (every media item whose id contains "{uuid}")
                if (count of theItems) = 0 then
                    error "Photo not found: {uuid}"
                end if
                spotlight (item 1 of theItems)
            end tell
            delay {delay}
            tell application "System Events"
                tell process "Photos"
                    keystroke "e" using command down
                end tell
            end tell
            delay {delay}
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                raise ClientError(f"Auto-enhance failed for {uuid}: {result.stderr.strip()}")

            return True

        except subprocess.TimeoutExpired:
            raise ClientError(f"Auto-enhance timed out for {uuid}")
        except Exception as e:
            if isinstance(e, ClientError):
                raise
            raise ClientError(f"Auto-enhance failed for {uuid}: {e}")

    def add_photos_to_album(self, album_name: str, photo_uuids: List[str]) -> int:
        """Add photos to an existing album.

        Uses AppleScript to add photos via Photos.app.

        Args:
            album_name: Name of the target album
            photo_uuids: List of photo UUIDs to add

        Returns:
            Number of photos successfully added

        Raises:
            ClientError: If album not found or operation fails
        """
        if not photo_uuids:
            return 0

        # Check if album exists
        existing = self._get_album_pk(album_name)
        if not existing:
            raise ClientError(f"Album '{album_name}' not found")

        # Escape quotes in album name for AppleScript
        escaped_name = album_name.replace('"', '\\"')

        # Build the condition to find photos by UUID
        # Photos IDs have format "UUID/L0/001", so we search for UUID prefix
        uuid_conditions = " or ".join([f'id contains "{uuid}"' for uuid in photo_uuids])

        script = f'''
            tell application "Photos"
                set theAlbum to first album whose name is "{escaped_name}"
                set theItems to (every media item whose {uuid_conditions})
                set itemCount to count of theItems
                if itemCount > 0 then
                    add theItems to theAlbum
                end if
                return itemCount
            end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout for large batches
            )

            if result.returncode != 0:
                raise ClientError(f"Failed to add photos to album: {result.stderr.strip()}")

            # Parse the count from output
            output = result.stdout.strip()
            try:
                return int(output)
            except ValueError:
                return 0

        except subprocess.TimeoutExpired:
            raise ClientError("Add photos operation timed out")
        except Exception as e:
            if isinstance(e, ClientError):
                raise
            raise ClientError(f"Failed to add photos to album: {e}")


# Module-level client instance - singleton pattern
_client: Optional[PhotosClient] = None


def get_client() -> PhotosClient:
    """Get or create the global Photos client instance."""
    global _client
    if _client is None:
        _client = PhotosClient()
    return _client
