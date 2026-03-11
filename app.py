import ctypes
import io
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout
from ctypes import wintypes
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd
from PIL import Image, ImageTk

from video_renamer.config import APP_DIR, load_app_config, resolve_path_setting, save_app_config
from video_renamer.constants import DEFAULT_VIDEO_FOLDER, FRAMES_ROOT, OUTPUT_DIR, THUMBS_ROOT, VIDEO_EXTS
from video_renamer.gemini import get_runtime_gemini_settings, test_api_key
from video_renamer.renaming import (
    build_rename_plan,
    execute_rename_plan,
    load_review_dataframe,
    save_review_dataframe,
)
from video_renamer.review_pipeline import ensure_workspace_dirs, run_review_pipeline


DISPLAY_COLUMNS = [
    "original_name",
    "proposed_label",
    "approved_label",
    "case_name",
    "confidence",
    "needs_review",
    "needs_case_review",
]
EDITABLE_COLUMNS = {"approved_label", "case_name"}
WM_DROPFILES = 0x0233
GWL_WNDPROC = -4


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, config: dict, on_save):
        super().__init__(parent)
        self.parent = parent
        self.on_save = on_save
        self.title("Settings")
        self.geometry("640x280")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.api_key_var = tk.StringVar(value=config.get("gemini_api_key", ""))
        self.model_var = tk.StringVar(value=config.get("model_name", ""))
        self.input_folder_var = tk.StringVar(value=config.get("default_input_folder", ""))
        self.output_folder_var = tk.StringVar(value=config.get("default_output_folder", ""))
        self.status_var = tk.StringVar(value="")
        self._testing = False

        self._build_ui()

    def _build_ui(self):
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Gemini API key").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        ttk.Entry(frame, textvariable=self.api_key_var, show="*").grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="Model name").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        ttk.Entry(frame, textvariable=self.model_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="Default input folder").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        ttk.Entry(frame, textvariable=self.input_folder_var).grid(row=2, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(frame, text="Browse", command=self._browse_input).grid(row=2, column=2, padx=(8, 0), pady=(0, 8))

        ttk.Label(frame, text="Default output folder").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        ttk.Entry(frame, textvariable=self.output_folder_var).grid(row=3, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(frame, text="Browse", command=self._browse_output).grid(row=3, column=2, padx=(8, 0), pady=(0, 8))

        ttk.Label(frame, textvariable=self.status_var, foreground="#0a5c0a").grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 8))

        button_row = ttk.Frame(frame)
        button_row.grid(row=5, column=0, columnspan=3, sticky="e")

        self.test_button = ttk.Button(button_row, text="Test API Key", command=self._test_api_key)
        self.test_button.pack(side="left", padx=(0, 8))
        ttk.Button(button_row, text="Save", command=self._save).pack(side="left", padx=(0, 8))
        ttk.Button(button_row, text="Cancel", command=self.destroy).pack(side="left")

    def _browse_input(self):
        folder = filedialog.askdirectory(initialdir=self.input_folder_var.get() or str(APP_DIR), parent=self)
        if folder:
            self.input_folder_var.set(folder)

    def _browse_output(self):
        folder = filedialog.askdirectory(initialdir=self.output_folder_var.get() or str(APP_DIR), parent=self)
        if folder:
            self.output_folder_var.set(folder)

    def _test_api_key(self):
        if self._testing:
            return

        api_key = self.api_key_var.get().strip()
        model_name = self.model_var.get().strip()
        if not api_key:
            messagebox.showerror("Missing API Key", "Enter a Gemini API key first.", parent=self)
            return
        if not model_name:
            messagebox.showerror("Missing Model", "Enter a model name first.", parent=self)
            return

        self._testing = True
        self.test_button.configure(state=tk.DISABLED)
        self.status_var.set("Testing API key...")

        def worker():
            success, message = test_api_key(api_key=api_key, model_name=model_name)
            self.after(0, lambda: self._finish_test(success, message))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_test(self, success: bool, message: str):
        self._testing = False
        self.test_button.configure(state=tk.NORMAL)
        self.status_var.set(message)
        if success:
            messagebox.showinfo("API Key Test", message, parent=self)
        else:
            messagebox.showerror("API Key Test Failed", message, parent=self)

    def _save(self):
        model_name = self.model_var.get().strip()
        input_folder = self.input_folder_var.get().strip()
        output_folder = self.output_folder_var.get().strip()

        if not model_name:
            messagebox.showerror("Missing Model", "Model name is required.", parent=self)
            return
        if not input_folder:
            messagebox.showerror("Missing Input Folder", "Default input folder is required.", parent=self)
            return
        if not output_folder:
            messagebox.showerror("Missing Output Folder", "Default output folder is required.", parent=self)
            return

        config = {
            "gemini_api_key": self.api_key_var.get().strip(),
            "model_name": model_name,
            "default_input_folder": input_folder,
            "default_output_folder": output_folder,
        }
        save_app_config(config)
        self.on_save(load_app_config())
        self.destroy()


class VideoRenamerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Video Renamer")
        self.geometry("1450x900")
        self.minsize(1180, 760)

        self.status_state_var = tk.StringVar(value="idle")
        self.status_detail_var = tk.StringVar(value="Select a video folder, then run the pipeline.")
        self.show_review_only = tk.BooleanVar(value=False)
        self.folder_summary_var = tk.StringVar(value="Supported videos found: 0")
        self.folder_warning_var = tk.StringVar(value="")
        self.folder_preview_title_var = tk.StringVar(value="Folder Preview")
        self.selected_folder = tk.StringVar()

        self.df = pd.DataFrame()
        self.rename_plan = []
        self.folder_videos = []
        self.photo_image = None
        self.edit_widget = None
        self.preview_window = None
        self._busy = False
        self._has_supported_videos = False
        self._folder_scan_after_id = None
        self._drag_drop_ready = False
        self._drop_wndproc = None
        self._old_wndproc = None
        self._user32 = None
        self._shell32 = None

        self.app_config = load_app_config()
        self.frames_root = FRAMES_ROOT
        self.thumbs_root = THUMBS_ROOT
        self.output_dir = OUTPUT_DIR
        self.csv_path = self.output_dir / "rename_review.csv"

        self._build_ui()
        self.selected_folder.trace_add("write", self._on_folder_var_changed)
        self._apply_config(self.app_config, update_selected_folder=True)
        self.after(100, self._install_drag_and_drop)
        self.after(150, self._refresh_folder_preview)
        self._set_status("idle", "Select a video folder, then run the pipeline.")

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=0)

        controls = ttk.Frame(self, padding=10)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Video Folder").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(controls, textvariable=self.selected_folder).grid(row=0, column=1, sticky="ew")
        ttk.Button(controls, text="Browse", command=self.choose_folder).grid(row=0, column=2, padx=(8, 0))
        self.run_pipeline_button = ttk.Button(controls, text="Run Pipeline", command=self.run_pipeline)
        self.run_pipeline_button.grid(row=0, column=3, padx=(12, 0))
        ttk.Button(controls, text="Load CSV", command=self.load_csv).grid(row=0, column=4, padx=(8, 0))
        ttk.Button(controls, text="Save CSV", command=self.save_csv).grid(row=0, column=5, padx=(8, 0))
        ttk.Button(controls, text="Preview Rename", command=self.preview_rename_plan).grid(row=0, column=6, padx=(8, 0))
        ttk.Button(controls, text="Execute Rename", command=self.execute_rename).grid(row=0, column=7, padx=(8, 0))
        ttk.Button(controls, text="Settings", command=self.open_settings).grid(row=0, column=8, padx=(8, 0))

        ttk.Checkbutton(
            controls,
            text="Show review rows only",
            variable=self.show_review_only,
            command=self._refresh_tree,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.csv_label = ttk.Label(controls, text="CSV:")
        self.csv_label.grid(row=1, column=2, columnspan=7, sticky="w", pady=(8, 0), padx=(8, 0))

        ttk.Label(
            controls,
            text="Tip: drag and drop a folder onto the window to set the video folder.",
        ).grid(row=2, column=0, columnspan=9, sticky="w", pady=(6, 0))

        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        table_frame = ttk.Frame(main)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        main.add(table_frame, weight=5)

        self.tree = ttk.Treeview(table_frame, columns=DISPLAY_COLUMNS, show="headings", selectmode="browse")
        for column in DISPLAY_COLUMNS:
            self.tree.heading(column, text=column)
            width = 190 if column in {"original_name", "approved_label", "case_name", "proposed_label"} else 110
            self.tree.column(column, width=width, anchor="w")

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        self.tree.tag_configure("review", background="#fff1cc")
        self.tree.bind("<Double-1>", self.begin_edit)
        self.tree.bind("<<TreeviewSelect>>", self.on_row_select)

        side = ttk.Frame(main, padding=(10, 0, 0, 0))
        side.columnconfigure(0, weight=1)
        side.rowconfigure(5, weight=1)
        main.add(side, weight=2)

        ttk.Label(side, text="Thumbnail Preview").grid(row=0, column=0, sticky="w")
        self.thumbnail_label = ttk.Label(side, text="No thumbnail", anchor="center", justify="center")
        self.thumbnail_label.grid(row=1, column=0, sticky="ew", pady=(8, 12))

        folder_panel = ttk.LabelFrame(side, text="Folder Contents", padding=8)
        folder_panel.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
        folder_panel.columnconfigure(0, weight=1)
        folder_panel.rowconfigure(3, weight=1)

        ttk.Label(folder_panel, textvariable=self.folder_summary_var).grid(row=0, column=0, sticky="w")
        ttk.Label(folder_panel, textvariable=self.folder_warning_var, foreground="#9a6700").grid(row=1, column=0, sticky="w", pady=(4, 4))
        ttk.Label(folder_panel, textvariable=self.folder_preview_title_var).grid(row=2, column=0, sticky="w", pady=(0, 4))

        list_frame = ttk.Frame(folder_panel)
        list_frame.grid(row=3, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.folder_listbox = tk.Listbox(list_frame, height=12)
        folder_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.folder_listbox.yview)
        self.folder_listbox.configure(yscrollcommand=folder_scroll.set)
        self.folder_listbox.grid(row=0, column=0, sticky="nsew")
        folder_scroll.grid(row=0, column=1, sticky="ns")
        self.folder_listbox.bind("<<ListboxSelect>>", self.on_folder_list_select)

        ttk.Label(side, text="Selected Row").grid(row=3, column=0, sticky="w")
        self.details_text = tk.Text(side, width=40, height=12, wrap="word", state="disabled")
        self.details_text.grid(row=4, column=0, sticky="nsew")

        log_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(2, weight=1)

        status_frame = ttk.Frame(log_frame)
        status_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        status_frame.columnconfigure(1, weight=1)

        ttk.Label(status_frame, text="State:").grid(row=0, column=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.status_state_var).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(status_frame, text="Status:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(status_frame, textvariable=self.status_detail_var).grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(4, 0))

        self.progress = ttk.Progressbar(log_frame, mode="indeterminate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self.log_text = tk.Text(log_frame, height=12, wrap="word")
        self.log_text.grid(row=2, column=0, sticky="nsew")

    def _apply_config(self, config: dict, update_selected_folder: bool = False):
        self.app_config = config
        default_input = resolve_path_setting(config.get("default_input_folder", ""), DEFAULT_VIDEO_FOLDER)
        self.output_dir = resolve_path_setting(config.get("default_output_folder", ""), OUTPUT_DIR)
        self.frames_root = FRAMES_ROOT
        self.thumbs_root = THUMBS_ROOT
        self.csv_path = self.output_dir / "rename_review.csv"
        ensure_workspace_dirs(frames_root=self.frames_root, thumbs_root=self.thumbs_root, output_dir=self.output_dir)

        if update_selected_folder or not self.selected_folder.get().strip():
            self.selected_folder.set(str(default_input))

        self.csv_label.config(text=f"CSV: {self.csv_path}")

    def open_settings(self):
        SettingsDialog(self, self.app_config.copy(), self._on_settings_saved)

    def _on_settings_saved(self, config: dict):
        self._apply_config(config, update_selected_folder=True)
        self._set_status("idle", "Settings saved.")
        self._refresh_folder_preview()

    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.selected_folder.get() or str(APP_DIR))
        if folder:
            self.selected_folder.set(folder)
            self._set_status("idle", f"Selected folder: {folder}")

    def run_pipeline(self):
        if self._busy:
            return

        folder = Path(self.selected_folder.get())
        if not folder.exists():
            self._set_status("error", "Select a valid video folder first.")
            messagebox.showerror("Missing Folder", "Select a valid video folder first.")
            return

        runtime = get_runtime_gemini_settings()
        if not runtime["api_key"]:
            self._set_status("error", "Gemini API key is missing. Open Settings to add it.")
            messagebox.showerror("Missing API Key", "Gemini API key is missing. Open Settings to add it.")
            return

        if not self._has_supported_videos:
            self._set_status("error", "No supported video files were found in the selected folder.")
            messagebox.showinfo("No Videos", "No supported video files were found in the selected folder.")
            return

        self._append_log(f"Running pipeline for {folder}")
        self._run_in_background(
            state="running pipeline",
            detail=f"Running pipeline for {folder}",
            target=self._run_pipeline_worker,
            args=(folder,),
            on_success=self._pipeline_finished,
        )

    def _run_pipeline_worker(self, folder: Path):
        valid, message = test_api_key()
        if not valid:
            raise ValueError(f"Gemini API key is missing or invalid: {message}")

        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            csv_path = run_review_pipeline(
                video_folder=folder,
                frames_root=self.frames_root,
                thumbs_root=self.thumbs_root,
                output_dir=self.output_dir,
                csv_path=self.csv_path,
            )
        return Path(csv_path), output.getvalue()

    def _pipeline_finished(self, result):
        csv_path, log_output = result
        if log_output.strip():
            self._append_log(log_output.strip())

        self.csv_path = csv_path or self.csv_path
        self.csv_label.config(text=f"CSV: {self.csv_path}")
        self._set_status("done", f"Pipeline completed. CSV saved to {self.csv_path}")
        self.load_csv()

    def load_csv(self):
        self._run_foreground_step("loading CSV", self._load_csv_impl)

    def _load_csv_impl(self):
        if not Path(self.csv_path).exists():
            raise FileNotFoundError(f"Could not find {self.csv_path}")

        self.df = load_review_dataframe(self.csv_path)
        self._refresh_tree()
        self._set_status("done", f"Loaded {len(self.df)} rows from {self.csv_path}")

    def save_csv(self):
        self._run_foreground_step("saving CSV", self._save_csv_impl)

    def _save_csv_impl(self):
        if self.df.empty:
            raise ValueError("Load or generate a CSV first.")

        save_review_dataframe(self.df, self.csv_path)
        self._append_log(f"Saved CSV: {self.csv_path}")
        self._set_status("done", f"Saved CSV to {self.csv_path}")

    def preview_rename_plan(self):
        self._run_foreground_step("previewing rename", self._preview_rename_impl)

    def _preview_rename_impl(self):
        if self.df.empty:
            raise ValueError("Load or generate a CSV first.")

        folder = Path(self.selected_folder.get())
        self.rename_plan = build_rename_plan(self.df, folder)
        self._show_preview_window()
        ready_count = sum(1 for item in self.rename_plan if item["status"] == "ready")
        self._set_status("done", f"Previewed rename plan: {ready_count} ready")

    def execute_rename(self):
        self._run_foreground_step("renaming files", self._execute_rename_impl)

    def _execute_rename_impl(self):
        if self.df.empty:
            raise ValueError("Load or generate a CSV first.")

        folder = Path(self.selected_folder.get())
        if not folder.exists():
            raise FileNotFoundError("Select a valid video folder first.")

        self.rename_plan = build_rename_plan(self.df, folder)
        ready_count = sum(1 for item in self.rename_plan if item["status"] == "ready")
        if ready_count == 0:
            raise ValueError("No ready items were found in the rename plan.")

        confirmed = messagebox.askyesno(
            "Execute Rename",
            f"Rename {ready_count} file(s) in:\n{folder}\n\nThis cannot be undone automatically.",
        )
        if not confirmed:
            self._set_status("idle", "Rename cancelled.")
            return

        results = execute_rename_plan(self.rename_plan, folder)
        renamed_count = sum(1 for item in results if item["result"] == "renamed")
        self._append_log(f"Renamed {renamed_count} file(s) in {folder}")
        self._set_status("done", f"Renamed {renamed_count} file(s)")
        messagebox.showinfo("Rename Complete", f"Renamed {renamed_count} file(s).")

    def _refresh_tree(self):
        selected = self.tree.selection()
        selected_id = selected[0] if selected else None

        self.tree.delete(*self.tree.get_children())
        if self.df.empty:
            self._update_details(None)
            self._show_folder_preview_thumbnail()
            return

        visible_df = self.df
        if self.show_review_only.get():
            mask = self.df.apply(self._is_review_row, axis=1)
            visible_df = self.df[mask]

        for index, row in visible_df.iterrows():
            values = [self._display_value(row.get(column, "")) for column in DISPLAY_COLUMNS]
            tags = ("review",) if self._is_review_row(row) else ()
            self.tree.insert("", "end", iid=str(index), values=values, tags=tags)

        if selected_id and self.tree.exists(selected_id):
            self.tree.selection_set(selected_id)
            self.on_row_select()
            return

        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.on_row_select()
        else:
            self._update_details(None)
            self._show_folder_preview_thumbnail()

    def _display_value(self, value):
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    def begin_edit(self, event):
        item_id = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        if not item_id or not column_id:
            return

        column_index = int(column_id.replace("#", "")) - 1
        if column_index < 0 or column_index >= len(DISPLAY_COLUMNS):
            return

        column_name = DISPLAY_COLUMNS[column_index]
        if column_name not in EDITABLE_COLUMNS:
            return

        bbox = self.tree.bbox(item_id, column_id)
        if not bbox:
            return

        if self.edit_widget is not None:
            self.edit_widget.destroy()

        x, y, width, height = bbox
        current_value = self.tree.set(item_id, column_name)

        editor = ttk.Entry(self.tree)
        editor.insert(0, current_value)
        editor.select_range(0, tk.END)
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()

        editor.bind("<Return>", lambda _event: self.finish_edit(item_id, column_name, editor.get()))
        editor.bind("<FocusOut>", lambda _event: self.finish_edit(item_id, column_name, editor.get()))
        editor.bind("<Escape>", lambda _event: self.cancel_edit())
        self.edit_widget = editor

    def finish_edit(self, item_id: str, column_name: str, value: str):
        if self.edit_widget is None:
            return

        self.df.at[int(item_id), column_name] = value.strip()
        self.tree.set(item_id, column_name, value.strip())
        self.edit_widget.destroy()
        self.edit_widget = None
        self._refresh_row(item_id)
        self._set_status("idle", f"Updated {column_name} for row {int(item_id) + 1}")
        self.on_row_select()

    def cancel_edit(self):
        if self.edit_widget is not None:
            self.edit_widget.destroy()
            self.edit_widget = None

    def _refresh_row(self, item_id: str):
        if not self.tree.exists(item_id):
            self._refresh_tree()
            return

        row = self.df.loc[int(item_id)]
        if self.show_review_only.get() and not self._is_review_row(row):
            self._refresh_tree()
            return

        values = [self._display_value(row.get(column, "")) for column in DISPLAY_COLUMNS]
        tags = ("review",) if self._is_review_row(row) else ()
        self.tree.item(item_id, values=values, tags=tags)

    def on_row_select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            self._update_details(None)
            self._show_folder_preview_thumbnail()
            return

        row_index = int(selection[0])
        row = self.df.loc[row_index]
        self._update_details(row)
        self._update_row_thumbnail(row)

    def on_folder_list_select(self, _event=None):
        selection = self.folder_listbox.curselection()
        if not selection:
            self._show_folder_preview_thumbnail()
            return

        index = selection[0]
        if 0 <= index < len(self.folder_videos):
            self._show_folder_video_preview(self.folder_videos[index])

    def _update_details(self, row):
        self.details_text.configure(state="normal")
        self.details_text.delete("1.0", tk.END)
        if row is not None:
            lines = [f"{column}: {row.get(column, '')}" for column in self.df.columns]
            self.details_text.insert("1.0", "\n".join(lines))
        self.details_text.configure(state="disabled")

    def _update_row_thumbnail(self, row):
        video_name = Path(str(row.get("original_name", ""))).name
        thumb_path = self.thumbs_root / f"{Path(video_name).stem}_mid.jpg"
        if thumb_path.exists():
            self._show_image_thumbnail(thumb_path)
            return

        self.thumbnail_label.configure(image="", text=f"No thumbnail available yet\n\n{video_name}")
        self.photo_image = None

    def _show_folder_preview_thumbnail(self):
        if self.folder_videos:
            self._show_folder_video_preview(self.folder_videos[0])
        else:
            self.thumbnail_label.configure(image="", text="No supported videos found")
            self.photo_image = None

    def _show_folder_video_preview(self, video_path: Path):
        thumb_path = self.thumbs_root / f"{video_path.stem}_mid.jpg"
        if thumb_path.exists():
            self._show_image_thumbnail(thumb_path)
            return

        self.thumbnail_label.configure(image="", text=f"No thumbnail yet\n\nFirst video:\n{video_path.name}")
        self.photo_image = None

    def _show_image_thumbnail(self, image_path: Path):
        with Image.open(image_path) as image:
            image.thumbnail((320, 240))
            preview = image.copy()

        self.photo_image = ImageTk.PhotoImage(preview)
        self.thumbnail_label.configure(image=self.photo_image, text="")

    def _show_preview_window(self):
        if self.preview_window is not None and self.preview_window.winfo_exists():
            self.preview_window.destroy()

        window = tk.Toplevel(self)
        window.title("Rename Preview")
        window.geometry("900x500")
        window.transient(self)

        columns = ("old_name", "new_name", "status", "case_name", "needs_case_review")
        tree = ttk.Treeview(window, columns=columns, show="headings")
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=180 if column in {"old_name", "new_name", "case_name"} else 120, anchor="w")

        tree.pack(fill="both", expand=True, padx=10, pady=10)

        for item in self.rename_plan:
            values = [item.get(column, "") for column in columns]
            tags = ("review",) if item.get("needs_case_review", False) else ()
            tree.insert("", "end", values=values, tags=tags)

        tree.tag_configure("review", background="#fff1cc")
        self.preview_window = window

    def _run_foreground_step(self, state: str, func):
        if self._busy:
            return

        self._set_busy(True, state, state)
        try:
            func()
        except FileNotFoundError as error:
            self._set_status("error", str(error))
            messagebox.showerror("Error", str(error))
        except ValueError as error:
            self._set_status("error", str(error))
            messagebox.showerror("Error", str(error))
        except Exception as error:
            self._set_status("error", str(error))
            messagebox.showerror("Error", str(error))
            self._append_log(traceback.format_exc())
        finally:
            self._set_busy(False)

    def _run_in_background(self, state: str, detail: str, target, args=(), on_success=None):
        if self._busy:
            return

        self._set_busy(True, state, detail)

        def worker():
            try:
                result = target(*args)
                self.after(0, lambda: self._background_success(on_success, result))
            except Exception as error:
                error_message = str(error) or "Operation failed"
                error_trace = traceback.format_exc()
                self.after(0, lambda: self._background_error(error_message, error_trace))

        threading.Thread(target=worker, daemon=True).start()

    def _background_success(self, on_success, result):
        self._set_busy(False)
        if on_success is not None:
            on_success(result)

    def _background_error(self, error_message: str, error_trace: str):
        self._set_busy(False)
        if error_trace.strip():
            self._append_log(error_trace.strip())
        self._set_status("error", error_message)
        messagebox.showerror("Error", error_message)

    def _set_busy(self, busy: bool, state: str | None = None, detail: str | None = None):
        self._busy = busy
        if state is not None or detail is not None:
            self._set_status(state or self.status_state_var.get(), detail or self.status_detail_var.get())

        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

        self._update_run_pipeline_state()

    def _set_status(self, state: str, detail: str):
        self.status_state_var.set(state)
        self.status_detail_var.set(detail)

    def _append_log(self, text: str):
        if not text:
            return
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)

    def _to_bool(self, value) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes", "y"}

    def _is_review_row(self, row) -> bool:
        return self._to_bool(row.get("needs_review", False)) or self._to_bool(row.get("needs_case_review", False))

    def _on_folder_var_changed(self, *_args):
        if self._folder_scan_after_id is not None:
            self.after_cancel(self._folder_scan_after_id)
        self._folder_scan_after_id = self.after(250, self._refresh_folder_preview)

    def _refresh_folder_preview(self):
        self._folder_scan_after_id = None
        folder_text = self.selected_folder.get().strip()
        folder = Path(folder_text) if folder_text else None

        self.folder_listbox.delete(0, tk.END)
        self.folder_videos = []

        if folder is None or not folder.exists() or not folder.is_dir():
            self.folder_summary_var.set("Supported videos found: 0")
            self.folder_warning_var.set("Select a valid folder to preview its contents.")
            self.folder_preview_title_var.set("Folder Preview")
            self._has_supported_videos = False
            self._update_run_pipeline_state()
            self.thumbnail_label.configure(image="", text="No supported videos found")
            self.photo_image = None
            return

        videos = sorted(
            [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in VIDEO_EXTS],
            key=lambda path: path.name.lower(),
        )
        self.folder_videos = videos
        self.folder_summary_var.set(f"Supported videos found: {len(videos)}")

        if not videos:
            self.folder_warning_var.set("No supported video files were found in this folder.")
            self.folder_preview_title_var.set("Folder Preview")
            self._has_supported_videos = False
            self._update_run_pipeline_state()
            self.thumbnail_label.configure(image="", text="No supported videos found")
            self.photo_image = None
            return

        self.folder_warning_var.set("")
        self.folder_preview_title_var.set(f"First video: {videos[0].name}")
        for video in videos:
            self.folder_listbox.insert(tk.END, video.name)

        self.folder_listbox.selection_clear(0, tk.END)
        self.folder_listbox.selection_set(0)
        self.folder_listbox.activate(0)
        self._has_supported_videos = True
        self._update_run_pipeline_state()
        self._show_folder_video_preview(videos[0])

    def _update_run_pipeline_state(self):
        state = tk.NORMAL if self._has_supported_videos and not self._busy else tk.DISABLED
        self.run_pipeline_button.configure(state=state)

    def _install_drag_and_drop(self):
        if self._drag_drop_ready:
            return

        try:
            self._user32 = ctypes.windll.user32
            self._shell32 = ctypes.windll.shell32
            hwnd = self.winfo_id()
            self._shell32.DragAcceptFiles(hwnd, True)

            wndproc_type = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            self._drop_wndproc = wndproc_type(self._window_proc)

            set_window_long = getattr(self._user32, "SetWindowLongPtrW", self._user32.SetWindowLongW)
            set_window_long.restype = ctypes.c_void_p
            set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            self._old_wndproc = set_window_long(
                hwnd,
                GWL_WNDPROC,
                ctypes.cast(self._drop_wndproc, ctypes.c_void_p).value,
            )
            self._drag_drop_ready = True
            self._append_log("Folder drag-and-drop is ready.")
        except Exception:
            self._append_log("Folder drag-and-drop is unavailable on this system.")

    def _window_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            self._handle_drop_files(wparam)
            return 0

        return self._call_original_wndproc(hwnd, msg, wparam, lparam)

    def _call_original_wndproc(self, hwnd, msg, wparam, lparam):
        if self._old_wndproc is None or self._user32 is None:
            return 0

        call_window_proc = self._user32.CallWindowProcW
        call_window_proc.restype = ctypes.c_ssize_t
        call_window_proc.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        return call_window_proc(self._old_wndproc, hwnd, msg, wparam, lparam)

    def _handle_drop_files(self, hdrop):
        if self._shell32 is None:
            return

        try:
            count = self._shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
            if count < 1:
                return

            length = self._shell32.DragQueryFileW(hdrop, 0, None, 0) + 1
            buffer = ctypes.create_unicode_buffer(length)
            self._shell32.DragQueryFileW(hdrop, 0, buffer, length)
            dropped_path = Path(buffer.value)

            if dropped_path.is_dir():
                self.selected_folder.set(str(dropped_path))
                self._set_status("idle", f"Selected folder from drag-and-drop: {dropped_path}")
            else:
                self._set_status("error", "Please drop a folder, not a file.")
        finally:
            self._shell32.DragFinish(hdrop)


if __name__ == "__main__":
    app = VideoRenamerApp()
    app.mainloop()

