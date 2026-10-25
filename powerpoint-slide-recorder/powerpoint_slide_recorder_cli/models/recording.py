"""Models returned by powerpoint-slide-recorder commands."""
from typing import List, Optional, Union

from .base import CLIModel


class SlideIdentity(CLIModel):
    """Slide identity for one recording item."""

    field: str
    value: Union[int, str]


class TimingAction(CLIModel):
    """Timed keyboard action sent during recording."""

    at_seconds: float
    key: str
    item: str
    slide: int
    reason: str


class RecordingItemPlan(CLIModel):
    """Prepared timing metadata for one input item."""

    label: str
    identity: SlideIdentity
    cue_count: int
    measured_click_steps: int
    audio: str
    duration_seconds: float
    audio_start_seconds: float
    cue_timing_method: str
    media_start: Optional[str] = None
    media_tail_seconds: Optional[float] = None


class TimingPlan(CLIModel):
    """Generated narration and action timing plan."""

    deck_path: str
    cue_marker: str
    narration_audio: str
    duration_seconds: float
    actions: List[TimingAction]
    items: List[RecordingItemPlan]


class RecordingResult(CLIModel):
    """Final result returned after a slide recording is recorded."""

    output_path: str
    timing_plan_path: str
    duration_seconds: float
    timing_plan: TimingPlan
