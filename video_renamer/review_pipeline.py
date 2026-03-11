from pathlib import Path

import pandas as pd

from video_renamer.clustering import cluster_videos_by_middle_frame
from video_renamer.constants import (
    DEFAULT_VIDEO_FOLDER,
    FRAMES_ROOT,
    OUTPUT_DIR,
    RENAME_REVIEW_CSV,
    REVIEW_COLUMNS,
    THUMBS_ROOT,
    VIDEO_EXTS,
)
from video_renamer.frame_extraction import extract_three_frames
from video_renamer.gemini import get_gemini_label
from video_renamer.labels import choose_case_label, sanitize_label, similarity_score


def auto_assign_case_names(rows: list[dict]) -> list[dict]:
    groups = []

    for index, row in enumerate(rows):
        label = sanitize_label(row.get("approved_label", ""))

        if label == "review_needed":
            groups.append(
                {
                    "labels": [label],
                    "row_indices": [index],
                    "case_name": "review_needed",
                }
            )
            continue

        best_group_idx = None
        best_score = -1.0

        for group_index, group in enumerate(groups):
            case_label = group["case_name"]
            score = similarity_score(label, case_label)
            if score > best_score:
                best_score = score
                best_group_idx = group_index

        if best_group_idx is not None and best_score >= 0.50:
            groups[best_group_idx]["labels"].append(label)
            groups[best_group_idx]["row_indices"].append(index)
            groups[best_group_idx]["case_name"] = choose_case_label(groups[best_group_idx]["labels"])
        else:
            groups.append(
                {
                    "labels": [label],
                    "row_indices": [index],
                    "case_name": choose_case_label([label]),
                }
            )

    for group in groups:
        case_name = group["case_name"]

        for row_idx in group["row_indices"]:
            label = sanitize_label(rows[row_idx].get("approved_label", ""))
            score = similarity_score(label, case_name)

            needs_review = False

            if label == "review_needed":
                needs_review = True
            elif score < 0.75 and label != case_name:
                needs_review = True
            elif rows[row_idx].get("needs_review", True):
                needs_review = True
            elif rows[row_idx].get("needs_visual_review", False):
                needs_review = True

            rows[row_idx]["case_name"] = case_name
            rows[row_idx]["needs_case_review"] = needs_review

    return rows


def ensure_workspace_dirs(
    frames_root: Path = FRAMES_ROOT,
    thumbs_root: Path = THUMBS_ROOT,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    frames_root.mkdir(exist_ok=True)
    thumbs_root.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)


def discover_videos(video_folder: Path = DEFAULT_VIDEO_FOLDER) -> list[Path]:
    videos = [path for path in video_folder.iterdir() if path.suffix.lower() in VIDEO_EXTS]
    return sorted(videos, key=lambda path: path.name.lower())


def build_review_rows(clusters: list[dict], per_video_info: dict, cluster_label_map: dict) -> list[dict]:
    rows = []
    idx_counter = 1

    for cluster in clusters:
        rep_video = cluster["representative"]
        rep_result = cluster_label_map.get(
            rep_video.name,
            {
                "proposed_label": "review_needed",
                "confidence": 0.0,
                "needs_review": True,
                "reason": "Missing representative result",
            },
        )

        for video in cluster["videos"]:
            visual_info = per_video_info.get(video.name, {})
            member_needs_review = bool(rep_result.get("needs_review", True)) or bool(
                visual_info.get("needs_visual_review", False)
            )

            rows.append(
                {
                    "index": idx_counter,
                    "original_name": video.name,
                    "original_path": str(video),
                    "proposed_label": sanitize_label(rep_result.get("proposed_label", "review_needed")),
                    "confidence": rep_result.get("confidence", 0.0),
                    "needs_review": member_needs_review,
                    "reason": rep_result.get("reason", ""),
                    "approved_label": sanitize_label(rep_result.get("proposed_label", "review_needed")),
                    "case_name": "",
                    "needs_case_review": False,
                    "visual_cluster_id": visual_info.get("visual_cluster_id", ""),
                    "visual_distance": visual_info.get("visual_distance", ""),
                    "is_representative": visual_info.get("representative", False),
                    "needs_visual_review": visual_info.get("needs_visual_review", False),
                }
            )

            idx_counter += 1

    return rows


def run_review_pipeline(
    video_folder: Path | str = DEFAULT_VIDEO_FOLDER,
    frames_root: Path | str = FRAMES_ROOT,
    thumbs_root: Path | str = THUMBS_ROOT,
    output_dir: Path | str = OUTPUT_DIR,
    csv_path: Path | str | None = None,
) -> Path:
    video_folder = Path(video_folder)
    frames_root = Path(frames_root)
    thumbs_root = Path(thumbs_root)
    output_dir = Path(output_dir)
    csv_path = Path(csv_path) if csv_path else output_dir / "rename_review.csv"

    ensure_workspace_dirs(frames_root=frames_root, thumbs_root=thumbs_root, output_dir=output_dir)

    videos = discover_videos(video_folder=video_folder)

    clusters, per_video_info = cluster_videos_by_middle_frame(
        videos=videos,
        thumb_root=thumbs_root,
        strong_threshold=6,
        borderline_threshold=10,
    )

    print(f"Found {len(videos)} video(s)")
    print(f"Visual clusters formed: {len(clusters)}")
    print(f"Estimated Gemini call reduction: {len(videos) - len(clusters)} saved")

    cluster_label_map = {}

    for cluster_idx, cluster in enumerate(clusters, start=1):
        rep_video = cluster["representative"]
        rep_name = rep_video.name

        print(f"\n[CLUSTER {cluster_idx}] Representative: {rep_name} | members={len(cluster['videos'])}")

        try:
            frame_dir = frames_root / rep_video.stem
            frame_paths = extract_three_frames(rep_video, frame_dir)

            if len(frame_paths) == 0:
                raise ValueError("No frames extracted for representative video")

            result = get_gemini_label(frame_paths)
            cluster_label_map[rep_name] = result

            if result.get("needs_review", True):
                print(f"[REVIEW] {rep_name} -> {result.get('proposed_label', 'review_needed')}")
            else:
                print(f"[OK] {rep_name} -> {result.get('proposed_label', 'review_needed')}")
        except Exception as error:
            cluster_label_map[rep_name] = {
                "proposed_label": "review_needed",
                "confidence": 0.0,
                "needs_review": True,
                "reason": f"Representative processing error: {error}",
            }
            print(f"[FAIL] Representative {rep_name}: {error}")

    rows = build_review_rows(clusters, per_video_info, cluster_label_map)
    rows = auto_assign_case_names(rows)

    for row in rows:
        if row["needs_case_review"]:
            print(
                f'[CASE REVIEW] {row["original_name"]} | '
                f'approved_label={row["approved_label"]} | '
                f'case_name={row["case_name"]}'
            )

    df = pd.DataFrame(rows)
    df = df[REVIEW_COLUMNS]
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"\nSaved review file to: {csv_path}")
    return csv_path


def main() -> None:
    run_review_pipeline(
        video_folder=DEFAULT_VIDEO_FOLDER,
        frames_root=FRAMES_ROOT,
        thumbs_root=THUMBS_ROOT,
        output_dir=OUTPUT_DIR,
        csv_path=RENAME_REVIEW_CSV,
    )
