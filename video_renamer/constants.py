from pathlib import Path

from video_renamer.config import APP_DIR


VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}

DEFAULT_VIDEO_FOLDER = APP_DIR / "Videos"
FRAMES_ROOT = APP_DIR / "frames"
THUMBS_ROOT = APP_DIR / "thumbs"
OUTPUT_DIR = APP_DIR / "output"
RENAME_REVIEW_CSV = OUTPUT_DIR / "rename_review.csv"

REVIEW_COLUMNS = [
    "index",
    "original_name",
    "original_path",
    "visual_cluster_id",
    "is_representative",
    "needs_visual_review",
    "visual_distance",
    "proposed_label",
    "confidence",
    "needs_review",
    "reason",
    "approved_label",
    "case_name",
    "needs_case_review",
]
