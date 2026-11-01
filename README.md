# Echo

Application for echocardiography analysis based on MedSAM2.

## Setup

- Python 3.14 (`.venv` links to the uv venv).
- Install with `pip install -e '.[seg]'` (viewer only: `pip install -e .`). CUDA is required; use a CUDA build of PyTorch.
- Install MedSAM2 (https://github.com/bowang-lab/MedSAM2). Its installed `sam2` package must provide `configs/sam2.1_hiera_t512.yaml`.
- Put MedSAM2 checkpoints (`MedSAM2*.pt`) in `checkpoints/MedSAM2/`. A symlink to the checkpoint directory is fine.

## Run

```bash
pip install -e '.[seg]'
python -m echo_seg      # or: echo-seg
```

## Viewer

- Run `python -m echo_viewer` (or `echo-viewer`) after `pip install -e .`.
- Click "Open session" and pick a session folder. Click a thumbnail to fill the active tile; a full tile is replaced by the next click.
- Play, Stop, Sync and Loop drive all visible tiles. Sync (default) runs them on one clock; Independent runs each at its own fps.
- The 1×1 / 2×2 selector switches layouts. In 1×1, click a tile to make it the shown one.
- `src/echo_viewer/ui/viewer_window.ui` is edited in Qt Designer and regenerated with `pyside6-uic src/echo_viewer/ui/viewer_window.ui -o src/echo_viewer/ui/ui_viewer_window.py`. Do not edit `ui_*.py` by hand.

## Layout

- `src/echo_core`: shared code (DICOM I/O, mask processing, pyqtgraph widgets). Apps import it; it imports no app.
- `src/echo_seg`: segmentation app. `src/echo_viewer`: DICOM viewer.
- `tests/{core,seg,viewer}`: tests per package. Run `pytest`.

## Data

- Example data lives in `data/` (anonymized DICOM).
- Planned data types: 2D, M-Mode, Doppler, 3D, Strain.

## Roadmap

- Phase 1: transition from the Medic (coronary) project. Done: SAM2 removed, MedSAM2 only.
- Phase 2: add point tracking and custom mask tracking. Done: custom mask tracking (spline outlines per keyframe, tracked backward and forward with MedSAM2). Todo: point tracking (per-frame trajectory of clicked points).


# Future Work
- Phase TBD: add support for M-Mode and Doppler data.
- Phase TBD: add support for 3D and Strain data.