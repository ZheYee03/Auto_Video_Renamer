from pathlib import Path

import cv2


def extract_middle_frame(video_path: str, output_path: str, resize_width: int = 256) -> str | None:
    """
    Extract one middle frame from a video and save it.
    Returns saved image path, or None if failed.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return None

    middle_pos = max(0, int(total_frames * 0.5))
    cap.set(cv2.CAP_PROP_POS_FRAMES, middle_pos)
    success, frame = cap.read()
    cap.release()

    if not success or frame is None:
        return None

    height, width = frame.shape[:2]
    if width > resize_width:
        new_height = int(height * (resize_width / width))
        frame = cv2.resize(frame, (resize_width, new_height))

    cv2.imwrite(str(output_path), frame)
    return str(output_path)


def extract_three_frames(video_path: str, output_dir: str):
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        raise ValueError(f"Could not read frame count: {video_path}")

    positions = [
        max(0, int(total_frames * 0.1)),
        max(0, int(total_frames * 0.5)),
        max(0, int(total_frames * 0.9)),
    ]

    saved_paths = []

    for index, pos in enumerate(positions, start=1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        success, frame = cap.read()
        if not success:
            continue

        out_path = output_dir / f"{video_path.stem}_frame{index}.jpg"
        cv2.imwrite(str(out_path), frame)
        saved_paths.append(str(out_path))

    cap.release()
    return saved_paths
