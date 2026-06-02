# How Gemini Understands Video

This document explains how the Gemini API processes video content, including frame sampling, audio processing, and best practices for prompting.

## Frame Sampling

### Default Behavior

- **1 frame per second (1 FPS)** is sampled from the video by default
- Gemini does NOT see every frame - a 7-minute video = ~420 frames analyzed
- Fast action sequences may lose detail due to this sampling rate
- Timestamps are added every second

### Customizing Frame Rate

You can override the default 1 FPS sampling:

```bash
# Higher FPS for fast-action or sync detection
gemini video analyze video.mp4 -p "Review this" --fps 3

# Lower FPS for long static videos (e.g., lectures)
gemini video analyze lecture.mp4 -p "Summarize" --fps 0.5
```

**When to use higher FPS (2-5):**
- Fast-action understanding
- High-speed motion tracking
- Detecting sync issues between audio and visuals
- Catching brief visual elements (< 1 second)

**When to use lower FPS (< 1):**
- Long static videos (lectures, presentations)
- Reducing token usage for lengthy content

## Token Calculation

Each second of video is tokenized as follows:

| Component | Tokens |
|-----------|--------|
| Video frame (default resolution) | 258 tokens/frame |
| Video frame (low resolution) | 66 tokens/frame |
| Audio | 32 tokens/second |
| Timestamps | 5 tokens |
| **Total (default resolution)** | **~300 tokens/second** |
| **Total (low resolution)** | **~100 tokens/second** |

### Capacity

- **1M context window models:** Up to 1 hour at default resolution, or 3 hours at low resolution
- **Gemini 3 improvements:** Variable sequence length tokenization (70 tokens/frame default)

## Audio Processing

### How Audio Works

- Audio is processed at **1Kbps single channel**
- Audio is broken into **1-second chunks** (32 tokens each)
- Audio tokens are **interleaved with video frames** along with timestamps
- The model CAN correlate what's being said with what's on screen

### Audio Capabilities

- Speech recognition and transcription
- Understanding spoken content in context with visuals
- Detecting audio quality issues (muffled, echo, background noise)

### Limitations

- Models may make mistakes recognizing **non-speech sounds**
- Complex audio mixing may not be accurately parsed

## Video Clipping

You can process only a portion of a video by specifying start and end offsets:

```python
from google.genai import types

# Clip a video from 1:00 to 3:00
video_part = types.Part(
    file_data=types.FileData(file_uri='...'),
    video_metadata=types.VideoMetadata(
        start_offset='60s',    # Start at 1:00
        end_offset='180s'      # End at 3:00
    )
)
```

**Benefits of clipping:**
- Reduce token usage
- Faster processing
- Focus on specific segments

## Best Practices

### Prompt Placement

1. **Place video before text prompt** in the request
2. Use only **one video per request** for optimal results
3. If combining text and video, place text prompt **after** the video

### Timestamp References

Use **MM:SS format** when referring to specific moments:

```
"What happens at 01:15?"
"Describe the transition between 02:30 and 02:45"
```

### Handling Fast Action

- At 1 FPS, sub-second events may be missed
- Consider **increasing FPS** for videos with quick transitions
- Alternatively, **slow down clips** during editing if FPS increase isn't sufficient

### Large Files

- Files < 20MB: Analyzed immediately via inline upload
- Files >= 20MB: Uploaded to Files API first, then processed
- Use `--no-wait` flag if you don't need immediate results for large files

## Supported Video Formats

- `video/mp4`
- `video/mpeg`
- `video/mov`
- `video/avi`
- `video/x-flv`
- `video/mpg`
- `video/webm`
- `video/wmv`
- `video/3gpp`

## Example: Course Video Review

For reviewing educational course videos where timing and sync matter:

```bash
# Use 3 FPS to better catch slide transitions and sync issues
gemini video analyze course-clip.mp4 \
  --prompt-file review_prompt.md \
  --files outline.pdf \
  --json-schema schema.json \
  --fps 3
```

## References

- [Video understanding | Gemini API | Google AI for Developers](https://ai.google.dev/gemini-api/docs/video-understanding)
- [Audio understanding | Gemini API](https://ai.google.dev/gemini-api/docs/audio)
- [Advancing the frontier of video understanding with Gemini 2.5](https://developers.googleblog.com/en/gemini-2-5-video-understanding/)
