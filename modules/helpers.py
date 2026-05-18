"""Helper utilities for the main application."""
import hashlib


def _uploaded_files_signature(files):
    """Generate a SHA1 signature of uploaded files for change detection.

    Args:
        files: List of uploaded file objects or None

    Returns:
        SHA1 hexdigest string, or empty string if no files
    """
    parts = []
    for idx, uploaded_file in enumerate(files or []):
        try:
            size = len(uploaded_file.getvalue())
        except Exception:
            size = 0
        parts.append(f"{idx}:{uploaded_file.name}:{size}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest() if parts else ""


def _reset_census_state(session_state):
    """Clear all Census batch processing state from session.

    Args:
        session_state: Streamlit session state dict
    """
    session_state['census_pending'] = False
    session_state['census_source_signature'] = ''
    session_state['census_stage_df'] = None
    session_state['census_original_df'] = None
    session_state['census_partial_calls_df'] = None
    session_state['_census_batch_started_at'] = None
    session_state['census_batch_zip_bytes'] = b""
    session_state['census_batch_zip_name'] = ""
    session_state['census_sample_bytes'] = b""
    session_state['census_sample_name'] = ""
    session_state['census_summary'] = {}
    session_state['census_conversion_summary'] = {}
    session_state['census_corrected_bytes'] = b""
    session_state['census_corrected_name'] = ""
    session_state['census_corrected_format'] = "csv"
    session_state['census_download_notice'] = False


def format_wait_duration(seconds):
    """Format seconds into a human-readable duration string.

    Args:
        seconds: Number of seconds (int or float)

    Returns:
        String like "2m 34s" or "45s"
    """
    seconds = max(0, int(seconds))
    mins, secs = divmod(seconds, 60)
    return f"{mins}m {secs:02d}s" if mins else f"{secs}s"
