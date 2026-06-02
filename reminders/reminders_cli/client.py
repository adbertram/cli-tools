"""macOS Reminders client using EventKit framework."""
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import time

try:
    import EventKit
    import Foundation
    import objc
except ImportError:
    print("Error: PyObjC is required for this CLI", file=sys.stderr)
    print("Install with: pip install pyobjc-framework-EventKit", file=sys.stderr)
    sys.exit(1)


class ClientError(Exception):
    """Custom exception for Reminders client errors."""
    pass


class RemindersClient:
    """Client for interacting with macOS Reminders via EventKit."""

    def __init__(self):
        """Initialize Reminders client and request permissions."""
        self.store = EventKit.EKEventStore.alloc().init()
        self._ensure_access()

    def _ensure_access(self):
        """Ensure we have access to Reminders."""
        # Check current authorization status
        status = EventKit.EKEventStore.authorizationStatusForEntityType_(
            EventKit.EKEntityTypeReminder
        )

        if status == EventKit.EKAuthorizationStatusAuthorized:
            return  # Already authorized

        if status == EventKit.EKAuthorizationStatusDenied:
            raise ClientError(
                "Access to Reminders denied. "
                "Please grant access in System Settings > Privacy & Security > Reminders"
            )

        if status == EventKit.EKAuthorizationStatusRestricted:
            raise ClientError("Access to Reminders is restricted on this device")

        # Request access
        if status == EventKit.EKAuthorizationStatusNotDetermined:
            access_granted = [False]  # Use list to allow modification in closure
            error_holder = [None]

            def completion(granted, error):
                access_granted[0] = granted
                error_holder[0] = error

            # Request access
            self.store.requestAccessToEntityType_completion_(
                EventKit.EKEntityTypeReminder,
                completion
            )

            # Wait for response (simple polling - PyObjC doesn't handle async well in CLI)
            for _ in range(50):  # Wait up to 5 seconds
                time.sleep(0.1)
                if access_granted[0] or error_holder[0]:
                    break

            if error_holder[0]:
                raise ClientError(f"Failed to request Reminders access: {error_holder[0]}")

            if not access_granted[0]:
                raise ClientError(
                    "Access to Reminders denied. "
                    "Please grant access in System Settings > Privacy & Security > Reminders"
                )

    def list_calendars(self) -> List[Dict]:
        """
        List all reminder lists (calendars).

        Returns:
            List of calendar dictionaries with id, title, color
        """
        calendars = self.store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)

        result = []
        for cal in calendars:
            result.append({
                "id": cal.calendarIdentifier(),
                "title": cal.title(),
                "color": self._color_to_hex(cal.color()) if cal.color() else None,
                "type": cal.type(),
                "allows_modification": cal.allowsContentModifications(),
            })

        return result

    def _color_to_hex(self, color) -> str:
        """Convert NSColor to hex string."""
        try:
            # Convert to RGB color space
            rgb_color = color.colorUsingColorSpace_(
                Foundation.NSColorSpace.sRGBColorSpace()
            )
            if rgb_color:
                r = int(rgb_color.redComponent() * 255)
                g = int(rgb_color.greenComponent() * 255)
                b = int(rgb_color.blueComponent() * 255)
                return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            pass
        return None

    def get_calendar(self, calendar_id: str) -> Optional[EventKit.EKCalendar]:
        """Get calendar by ID."""
        return self.store.calendarWithIdentifier_(calendar_id)

    def get_default_calendar(self) -> EventKit.EKCalendar:
        """Get the default reminders calendar."""
        return self.store.defaultCalendarForNewReminders()

    def list_reminders(
        self,
        calendar_id: Optional[str] = None,
        completed: Optional[bool] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        List reminders with optional filtering.

        Args:
            calendar_id: Filter by specific calendar ID
            completed: Filter by completion status (True=completed, False=incomplete, None=all)
            limit: Maximum number of reminders to return

        Returns:
            List of reminder dictionaries
        """
        # Build predicate
        calendars = None
        if calendar_id:
            cal = self.get_calendar(calendar_id)
            if not cal:
                raise ClientError(f"Calendar not found: {calendar_id}")
            calendars = [cal]

        # Fetch reminders using predicate
        predicate = self.store.predicateForRemindersInCalendars_(calendars)

        reminders_holder = []

        def completion(reminders):
            if reminders:
                reminders_holder.extend(reminders)

        # Fetch reminders
        self.store.fetchRemindersMatchingPredicate_completion_(predicate, completion)

        # Wait for fetch to complete (PyObjC async handling)
        for _ in range(50):  # Wait up to 5 seconds
            time.sleep(0.1)
            if reminders_holder:
                break

        # Filter by completion status if specified
        filtered_reminders = []
        for reminder in reminders_holder:
            if completed is not None:
                if completed and not reminder.isCompleted():
                    continue
                if not completed and reminder.isCompleted():
                    continue
            filtered_reminders.append(reminder)

        # Apply limit if specified
        if limit:
            filtered_reminders = filtered_reminders[:limit]

        # Convert to dictionaries
        return [self._reminder_to_dict(r) for r in filtered_reminders]

    def _extract_tags(self, text: str) -> List[str]:
        """Extract hashtags from text (title or notes)."""
        if not text:
            return []
        # Match hashtags: # followed by word characters, but not just numbers
        pattern = r'#([a-zA-Z][a-zA-Z0-9_]*)'
        return re.findall(pattern, text)

    def _remove_tags_from_title(self, title: str) -> str:
        """Remove leading hashtags from title to get clean title."""
        if not title:
            return ""
        # Remove hashtags at the start of the title (with optional spaces)
        cleaned = re.sub(r'^(\s*#[a-zA-Z][a-zA-Z0-9_]*\s*)+', '', title)
        return cleaned.strip()

    def _reminder_to_dict(self, reminder: EventKit.EKReminder) -> Dict:
        """Convert EKReminder to dictionary."""
        title = reminder.title() or ""
        notes = reminder.notes() or ""

        # Extract tags from title
        tags = self._extract_tags(title)

        # Get clean title without leading tags
        clean_title = self._remove_tags_from_title(title)

        result = {
            "id": reminder.calendarItemIdentifier(),
            "title": clean_title,
            "title_raw": title,  # Original title with tags
            "tags": tags,
            "completed": reminder.isCompleted(),
            "calendar_id": reminder.calendar().calendarIdentifier(),
            "calendar_title": reminder.calendar().title(),
            "priority": reminder.priority(),
            "notes": notes,
        }

        # Add due date if present
        if reminder.dueDateComponents():
            due_date = reminder.dueDateComponents()
            try:
                # Convert NSDateComponents to datetime
                calendar = Foundation.NSCalendar.currentCalendar()
                ns_date = calendar.dateFromComponents_(due_date)
                if ns_date:
                    # Convert NSDate to Python datetime
                    timestamp = ns_date.timeIntervalSince1970()
                    dt = datetime.fromtimestamp(timestamp)
                    result["due_date"] = dt.isoformat()
            except Exception:
                pass

        # Add start date if present (when task becomes actionable)
        if reminder.startDateComponents():
            start_date = reminder.startDateComponents()
            try:
                calendar = Foundation.NSCalendar.currentCalendar()
                ns_date = calendar.dateFromComponents_(start_date)
                if ns_date:
                    timestamp = ns_date.timeIntervalSince1970()
                    dt = datetime.fromtimestamp(timestamp)
                    result["start_date"] = dt.isoformat()
            except Exception:
                pass

        # Add completion date if completed
        if reminder.completionDate():
            timestamp = reminder.completionDate().timeIntervalSince1970()
            dt = datetime.fromtimestamp(timestamp)
            result["completed_date"] = dt.isoformat()

        # Add creation date
        if reminder.creationDate():
            timestamp = reminder.creationDate().timeIntervalSince1970()
            dt = datetime.fromtimestamp(timestamp)
            result["created_date"] = dt.isoformat()

        return result

    def get_reminder(self, reminder_id: str) -> Optional[Dict]:
        """
        Get a specific reminder by ID.

        Args:
            reminder_id: The reminder calendar item identifier

        Returns:
            Reminder dictionary or None if not found
        """
        reminder = self.store.calendarItemWithIdentifier_(reminder_id)
        if reminder and isinstance(reminder, EventKit.EKReminder):
            return self._reminder_to_dict(reminder)
        return None

    def create_reminder(
        self,
        title: str,
        calendar_id: Optional[str] = None,
        notes: Optional[str] = None,
        due_date: Optional[datetime] = None,
        priority: int = 0,
        tags: Optional[List[str]] = None,
    ) -> Dict:
        """
        Create a new reminder.

        Args:
            title: Reminder title
            calendar_id: Calendar ID (uses default if not specified)
            notes: Optional notes
            due_date: Optional due date
            priority: Priority (0=none, 1=high, 5=medium, 9=low)
            tags: Optional list of tags (without # prefix)

        Returns:
            Created reminder dictionary
        """
        # Get calendar
        if calendar_id:
            calendar = self.get_calendar(calendar_id)
            if not calendar:
                raise ClientError(f"Calendar not found: {calendar_id}")
        else:
            calendar = self.get_default_calendar()

        if not calendar:
            raise ClientError("No calendar available for creating reminders")

        # Build title with tags prepended
        full_title = title
        if tags:
            tag_prefix = " ".join(f"#{tag.lstrip('#')}" for tag in tags)
            full_title = f"{tag_prefix} {title}"

        # Create reminder
        reminder = EventKit.EKReminder.reminderWithEventStore_(self.store)
        reminder.setTitle_(full_title)
        reminder.setCalendar_(calendar)

        if notes:
            reminder.setNotes_(notes)

        if priority:
            reminder.setPriority_(priority)

        # Set due date if provided
        if due_date:
            components = Foundation.NSDateComponents.alloc().init()
            components.setYear_(due_date.year)
            components.setMonth_(due_date.month)
            components.setDay_(due_date.day)
            components.setHour_(due_date.hour)
            components.setMinute_(due_date.minute)
            reminder.setDueDateComponents_(components)

        # Save reminder
        error = objc.nil
        success = self.store.saveReminder_commit_error_(reminder, True, objc.nil)

        if not success:
            raise ClientError(f"Failed to create reminder: {error}")

        return self._reminder_to_dict(reminder)

    def complete_reminder(self, reminder_id: str) -> Dict:
        """
        Mark a reminder as completed.

        Args:
            reminder_id: The reminder calendar item identifier

        Returns:
            Updated reminder dictionary
        """
        reminder = self.store.calendarItemWithIdentifier_(reminder_id)
        if not reminder or not isinstance(reminder, EventKit.EKReminder):
            raise ClientError(f"Reminder not found: {reminder_id}")

        reminder.setCompleted_(True)

        success = self.store.saveReminder_commit_error_(reminder, True, objc.nil)
        if not success:
            raise ClientError("Failed to complete reminder")

        return self._reminder_to_dict(reminder)

    def uncomplete_reminder(self, reminder_id: str) -> Dict:
        """
        Mark a reminder as incomplete.

        Args:
            reminder_id: The reminder calendar item identifier

        Returns:
            Updated reminder dictionary
        """
        reminder = self.store.calendarItemWithIdentifier_(reminder_id)
        if not reminder or not isinstance(reminder, EventKit.EKReminder):
            raise ClientError(f"Reminder not found: {reminder_id}")

        reminder.setCompleted_(False)

        success = self.store.saveReminder_commit_error_(reminder, True, objc.nil)
        if not success:
            raise ClientError("Failed to uncomplete reminder")

        return self._reminder_to_dict(reminder)

    def delete_reminder(self, reminder_id: str) -> bool:
        """
        Delete a reminder.

        Args:
            reminder_id: The reminder calendar item identifier

        Returns:
            True if deleted successfully
        """
        reminder = self.store.calendarItemWithIdentifier_(reminder_id)
        if not reminder or not isinstance(reminder, EventKit.EKReminder):
            raise ClientError(f"Reminder not found: {reminder_id}")

        success = self.store.removeReminder_commit_error_(reminder, True, objc.nil)
        if not success:
            raise ClientError("Failed to delete reminder")

        return True


# Module-level client instance - singleton pattern
_client: Optional[RemindersClient] = None


def get_client() -> RemindersClient:
    """Get or create the global Reminders client instance."""
    global _client
    if _client is None:
        _client = RemindersClient()
    return _client
