# Video Renamer

Windows-friendly Tkinter desktop app for clustering, reviewing, and renaming short videos with Gemini-assisted labels.

## Setup

1. Copy `config.example.json` to `config.json`.
2. Open `config.json` and paste your Gemini API key into `gemini_api_key`.
3. Optionally change the default input and output folders. The project uses `Videos` as the neutral default input folder.
4. Install dependencies with `pip install -r requirements.txt`.
5. Run the app locally with `python app.py`.

Notes:
- `config.json` is for local runtime settings only and is ignored by Git.
- The app reads real runtime settings from local `config.json` beside the app.
- When packaged, the app still reads and writes `config.json` beside `VideoRenamer.exe`.

## Workflow

1. Choose any folder that contains short video files.
2. Run the pipeline to cluster similar videos, extract frames, label cluster representatives with Gemini, and generate `rename_review.csv`.
3. Review or edit labels in the app or CSV.
4. Preview the rename plan and execute the rename when ready.

## Build Executable

1. Open a Command Prompt in this project folder.
2. Install PyInstaller if needed:
   `pip install pyinstaller`
3. Run the build script:
   `build_exe.bat`
4. After the build finishes, the executable will be available at:
   `dist\VideoRenamer.exe`

Notes:
- The build uses PyInstaller with `--onefile`, `--windowed`, and `--name VideoRenamer`.
- Runtime folders are created automatically when the app starts if they are missing: `output`, `frames`, and `thumbs`.
- The default sample input folder is `Videos`, but you can point the app at any folder you want to process.
