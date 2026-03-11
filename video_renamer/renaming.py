from pathlib import Path

import pandas as pd

from video_renamer.constants import DEFAULT_VIDEO_FOLDER, RENAME_REVIEW_CSV
from video_renamer.labels import choose_case_label, clean_optional_label, labels_are_similar, sanitize_label


def normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y"}


def load_review_dataframe(csv_path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    for col in df.columns:
        df[col] = df[col].fillna("")
    if "needs_case_review" in df.columns:
        df["needs_case_review"] = df["needs_case_review"].apply(normalize_bool)
    if "needs_review" in df.columns:
        df["needs_review"] = df["needs_review"].apply(normalize_bool)
    return df


def save_review_dataframe(df: pd.DataFrame, csv_path: str | Path) -> Path:
    csv_path = Path(csv_path)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


def build_groups(df: pd.DataFrame) -> list[dict]:
    groups = []

    for index, row in df.iterrows():
        approved_label = sanitize_label(str(row.get("approved_label", "")))
        case_name = clean_optional_label(row.get("case_name", "")) if "case_name" in df.columns else ""

        if case_name:
            placed = False
            for group in groups:
                if group["case_name"] == case_name:
                    group["rows"].append(index)
                    group["labels"].append(approved_label)
                    placed = True
                    break

            if not placed:
                groups.append(
                    {
                        "rows": [index],
                        "labels": [approved_label],
                        "case_name": case_name,
                    }
                )
            continue

        placed = False
        for group in groups:
            group_case = group["case_name"] if group["case_name"] else choose_case_label(group["labels"])
            if labels_are_similar(approved_label, group_case):
                group["rows"].append(index)
                group["labels"].append(approved_label)
                placed = True
                break

        if not placed:
            groups.append(
                {
                    "rows": [index],
                    "labels": [approved_label],
                    "case_name": "",
                }
            )

    return groups


def build_unique_name(folder: Path, desired_name: str) -> str:
    candidate = desired_name
    stem = Path(desired_name).stem
    suffix = Path(desired_name).suffix
    counter = 1

    while (folder / candidate).exists():
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1

    return candidate


def build_rename_plan(df: pd.DataFrame, folder: Path | str) -> list[dict]:
    folder = Path(folder)
    groups = build_groups(df)
    rename_plan = []

    for case_idx, group in enumerate(groups, start=1):
        case_label = group["case_name"] if group["case_name"] else choose_case_label(group["labels"])

        for sub_idx, row_idx in enumerate(group["rows"]):
            row = df.loc[row_idx]
            old_name = str(row["original_name"]).strip()
            old_path = folder / old_name
            needs_case_review = normalize_bool(row.get("needs_case_review", False))

            if not old_path.exists():
                rename_plan.append(
                    {
                        "old_name": old_name,
                        "new_name": "",
                        "status": "missing_file",
                        "case_name": case_label,
                        "needs_case_review": needs_case_review,
                    }
                )
                continue

            new_name = f"{case_idx}.{sub_idx}_{case_label}{old_path.suffix.lower()}"
            new_name = build_unique_name(folder, new_name)

            rename_plan.append(
                {
                    "old_name": old_name,
                    "new_name": new_name,
                    "status": "ready",
                    "case_name": case_label,
                    "needs_case_review": needs_case_review,
                }
            )

    return rename_plan


def build_rename_plan_from_csv(csv_path: str | Path, folder: Path | str) -> list[dict]:
    df = load_review_dataframe(csv_path)
    return build_rename_plan(df, folder)


def print_preview_table(rename_plan: list[dict]):
    print("\nRENAME PREVIEW")
    print("-" * 100)
    print(f"{'OLD NAME':40} {'NEW NAME':40} {'STATUS':10} {'REVIEW'}")
    print("-" * 100)

    for item in rename_plan:
        old_name = item["old_name"][:40]
        new_name = item["new_name"][:40] if item["new_name"] else ""
        status = item["status"]
        review = "YES" if item.get("needs_case_review", False) else ""
        print(f"{old_name:40} {new_name:40} {status:10} {review}")

    print("-" * 100)


def execute_rename_plan(rename_plan: list[dict], folder: Path | str) -> list[dict]:
    folder = Path(folder)
    results = []

    for item in rename_plan:
        if item["status"] != "ready":
            results.append({**item, "result": "skipped"})
            continue

        old_path = folder / item["old_name"]
        new_path = folder / item["new_name"]

        if not old_path.exists():
            results.append({**item, "result": "skipped"})
            continue

        old_path.rename(new_path)
        results.append({**item, "result": "renamed"})

    return results


def rename_from_csv(csv_path: str | Path, folder: Path | str = DEFAULT_VIDEO_FOLDER):
    csv_file = Path(csv_path)
    folder = Path(folder)

    if not csv_file.exists():
        print(f"CSV not found: {csv_path}")
        return

    if not folder.exists():
        print(f"Video folder not found: {folder}")
        return

    df = load_review_dataframe(csv_file)

    if "needs_case_review" in df.columns:
        flagged = df[df["needs_case_review"]]

        if len(flagged) > 0:
            print(f"\nWARNING: {len(flagged)} row(s) are flagged for case review:")
            for _, row in flagged.iterrows():
                print(
                    f'- {row["original_name"]}: '
                    f'approved_label={row.get("approved_label", "")}, '
                    f'case_name={row.get("case_name", "")}'
                )

    rename_plan = build_rename_plan(df, folder)
    print_preview_table(rename_plan)

    ready_count = sum(1 for item in rename_plan if item["status"] == "ready")
    missing_count = sum(1 for item in rename_plan if item["status"] == "missing_file")
    review_count = sum(1 for item in rename_plan if item.get("needs_case_review", False))

    print(
        f"\nSummary: {ready_count} ready, "
        f"{missing_count} missing, "
        f"{review_count} flagged for review"
    )

    proceed = input("Proceed with renaming? (y/n): ").strip().lower()
    if proceed != "y":
        print("Rename cancelled.")
        return

    results = execute_rename_plan(rename_plan, folder)
    for item in results:
        if item["result"] == "skipped":
            print(f"Skip missing file: {item['old_name']}")
        else:
            print(f"Renamed: {item['old_name']} -> {item['new_name']}")


def main() -> None:
    rename_from_csv(str(RENAME_REVIEW_CSV), folder=DEFAULT_VIDEO_FOLDER)
