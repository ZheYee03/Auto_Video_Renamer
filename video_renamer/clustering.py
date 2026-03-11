from pathlib import Path

import imagehash
from PIL import Image

from video_renamer.frame_extraction import extract_middle_frame


def compute_frame_hash(image_path: str):
    """
    Compute perceptual hash for one image.
    """
    img = Image.open(image_path)
    try:
        return imagehash.phash(img)
    finally:
        img.close()


def hash_distance(hash1, hash2) -> int:
    return hash1 - hash2


def choose_cluster_label_name(video_names: list[str]) -> str:
    """
    Temporary visual cluster label for debugging only.
    """
    if not video_names:
        return "cluster"
    return Path(video_names[0]).stem


def cluster_videos_by_middle_frame(
    videos: list[Path],
    thumb_root: Path,
    strong_threshold: int = 6,
    borderline_threshold: int = 10,
) -> tuple[list[dict], dict]:
    """
    Returns:
    - clusters: list of clusters
    - per_video_info: mapping of video name -> clustering info

    Threshold meaning:
    - distance <= strong_threshold: same cluster confidently
    - strong_threshold < distance <= borderline_threshold: same cluster but review
    - distance > borderline_threshold: separate cluster
    """
    thumb_root.mkdir(parents=True, exist_ok=True)

    video_items = []
    per_video_info = {}

    for video in videos:
        thumb_path = thumb_root / f"{video.stem}_mid.jpg"
        saved = extract_middle_frame(video, thumb_path)

        if not saved:
            video_items.append(
                {
                    "video": video,
                    "thumb_path": "",
                    "hash": None,
                    "hash_error": True,
                }
            )
            per_video_info[video.name] = {
                "visual_cluster_id": -1,
                "needs_visual_review": True,
                "visual_distance": "",
                "representative": False,
                "thumb_path": "",
            }
            continue

        try:
            phash = compute_frame_hash(saved)
            video_items.append(
                {
                    "video": video,
                    "thumb_path": str(thumb_path),
                    "hash": phash,
                    "hash_error": False,
                }
            )
        except Exception:
            video_items.append(
                {
                    "video": video,
                    "thumb_path": str(thumb_path),
                    "hash": None,
                    "hash_error": True,
                }
            )

    clusters = []

    for item in video_items:
        video = item["video"]

        if item["hash_error"] or item["hash"] is None:
            clusters.append(
                {
                    "videos": [video],
                    "representative": video,
                    "representative_hash": None,
                    "needs_visual_review": True,
                    "members_need_review": {video.name: True},
                    "member_distances": {video.name: ""},
                }
            )
            continue

        best_cluster_idx = None
        best_distance = 10**9

        for cluster_index, cluster in enumerate(clusters):
            rep_hash = cluster["representative_hash"]
            if rep_hash is None:
                continue

            distance = hash_distance(item["hash"], rep_hash)
            if distance < best_distance:
                best_distance = distance
                best_cluster_idx = cluster_index

        if best_cluster_idx is not None and best_distance <= borderline_threshold:
            cluster = clusters[best_cluster_idx]
            cluster["videos"].append(video)
            cluster["member_distances"][video.name] = best_distance

            if best_distance > strong_threshold:
                cluster["needs_visual_review"] = True
                cluster["members_need_review"][video.name] = True
            else:
                cluster["members_need_review"][video.name] = False
        else:
            clusters.append(
                {
                    "videos": [video],
                    "representative": video,
                    "representative_hash": item["hash"],
                    "needs_visual_review": False,
                    "members_need_review": {video.name: False},
                    "member_distances": {video.name: 0},
                }
            )

    for cluster_idx, cluster in enumerate(clusters, start=1):
        rep_name = cluster["representative"].name

        for video in cluster["videos"]:
            per_video_info[video.name] = {
                "visual_cluster_id": cluster_idx,
                "needs_visual_review": cluster["members_need_review"].get(video.name, False),
                "visual_distance": cluster["member_distances"].get(video.name, ""),
                "representative": video.name == rep_name,
                "thumb_path": str(thumb_root / f"{video.stem}_mid.jpg"),
            }

    return clusters, per_video_info
