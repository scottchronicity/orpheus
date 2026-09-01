# ADR 0004: Jetson Video Codec Strategy (mp4v + ffmpeg Transcode)

**Status:** Accepted

**Date:** 2026-01-25

**Deciders:** Development Team

## Context

Timelapse videos generated on the NVIDIA Jetson Orin NX needed to be playable in modern web browsers (Chrome, Firefox, Safari). We encountered critical issues with video encoding:

### The Problem

1. **OpenCV H.264 codecs failed silently on Jetson**:
   - `avc1` codec: Created files that appeared valid but displayed as green screens
   - `H264` codec: Similar silent failures
   - Both codecs worked correctly on macOS development machines

2. **Root cause investigation**:
   - Jetson uses pip-installed OpenCV (opencv-python-headless)
   - This OpenCV build has broken or missing GStreamer plugins
   - The H.264 encoding path silently produces corrupted video data

3. **mp4v (MPEG-4 Part 2) worked but had issues**:
   - Videos encoded correctly (no green screen)
   - Poor browser compatibility (some browsers struggle with MPEG-4 Part 2)
   - Larger file sizes compared to H.264

### Requirements

- Videos must play in all modern browsers (dashboard playback)
- Must work reliably on Jetson Orin NX (ARM64, Ubuntu 20.04)
- Reasonable file sizes for storage management
- No external Python dependencies beyond what's already installed

## Decision

### Two-Phase Encoding Strategy

1. **Phase 1: Write video with mp4v (OpenCV)**
   - Use `cv2.VideoWriter` with `mp4v` fourcc code
   - This reliably creates valid video files on Jetson
   - No codec fallback loop (removed avc1/H264 attempts)

2. **Phase 2: Transcode to H.264 (system ffmpeg)**
   - Use system `/usr/bin/ffmpeg` with libx264
   - Produces universally compatible H.264 MP4 files
   - Replace original mp4v file with transcoded version

### Implementation

```python
def _transcode_to_h264(self, video_path: Path, camera_name: str) -> bool:
    """Transcode mp4v video to H.264 using system ffmpeg."""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        logger.warning("ffmpeg not found, skipping transcode")
        return False

    temp_path = video_path.with_suffix(".h264.mp4")
    cmd = [
        ffmpeg_path,
        "-y",                    # Overwrite output
        "-i", str(video_path),   # Input file
        "-c:v", "libx264",       # H.264 codec
        "-preset", "fast",       # Balance speed/quality
        "-crf", "28",            # Quality (28 = good for timelapses)
        "-movflags", "+faststart",  # Enable streaming
        str(temp_path),
    ]
    
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode == 0:
        shutil.move(temp_path, video_path)  # Replace original
        return True
    return False
```

### Quality Settings

- **CRF 28**: Provides good quality for timelapse overview videos at ~50% smaller file size vs CRF 23 (default)
- **Preset fast**: Balances encoding speed with compression efficiency
- **movflags +faststart**: Enables progressive playback without downloading entire file

### Fallback Behavior

If ffmpeg is not available:

- Log a warning
- Keep the mp4v-encoded file (better than no video)
- Videos may not play in all browsers

## Consequences

### Positive

- **Reliable encoding**: mp4v never produces green screens on Jetson
- **Universal playback**: H.264 works in all modern browsers
- **Smaller files**: CRF 28 reduces storage requirements by ~50%
- **No Python dependencies**: Uses system ffmpeg (already installed on Jetson)
- **Graceful degradation**: Works without ffmpeg, just with reduced compatibility

### Negative

- **Two-phase processing**: Slightly longer generation time (write + transcode)
- **Disk I/O**: Temporary file written during transcode
- **External dependency**: Requires system ffmpeg for optimal results

### Neutral

- **Removed codec fallback loop**: Simpler code, but no automatic H.264 attempt via OpenCV
- **File size increase**: mp4v temp files are larger before transcode (deleted after)

## Why Not Other Approaches?

### 1. Install OpenCV with GStreamer support

Rejected: Would require building OpenCV from source on Jetson, complex maintenance, potential compatibility issues with other Python packages.

### 2. Use hardware encoder (NVENC)

Considered for future: Jetson has hardware H.264 encoding, but requires GStreamer pipeline or specific OpenCV build. Current approach is simpler and reliable.

### 3. Use PyAV or other Python video libraries

Rejected: Would add new dependencies, increase complexity. System ffmpeg is already available and well-tested.

### 4. Keep mp4v without transcoding

Rejected: Browser compatibility issues. Safari and some mobile browsers struggle with MPEG-4 Part 2.

## Verification

After deployment, verify codec with:

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name \
  -of default=noprint_wrappers=1:nokey=1 /path/to/timelapse.mp4
```

Expected output: `h264`

## Related

- [ADR 0003: Timelapse Generation Architecture](0003-timelapse-generation-architecture.md)
- [agents/orpheus-agent-video-timelapser/README.md](https://github.com/scottchronicity/orpheus/blob/main/agents/orpheus-agent-video-timelapser/README.md)
- [docs/ARCHITECTURE.md](../ARCHITECTURE.md)
