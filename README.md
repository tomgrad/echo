# Echo

Application for echocardiography analysis based on MedSAM2.

## Setup

- Python 3.14 (`.venv` links to the uv venv).
- Install dependencies from `requirements.txt`. CUDA is required; use a CUDA build of PyTorch.
- Install MedSAM2 (https://github.com/bowang-lab/MedSAM2). Its installed `sam2` package must provide `configs/sam2.1_hiera_t512.yaml`.
- Put MedSAM2 checkpoints (`MedSAM2*.pt`) in `checkpoints/MedSAM2/`. A symlink to the checkpoint directory is fine.

## Run

```bash
python main.py
```

## Data

- Example data lives in `data/` (anonymized DICOM).
- Planned data types: 2D, M-Mode, Doppler, 3D, Strain.

## Roadmap

- Phase 1: transition from the Medic (coronary) project. Done: SAM2 removed, MedSAM2 only.
