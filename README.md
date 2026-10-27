# Echo

Goal: create an application for echocardiography analysis based on MedSAM2 models.

Phase 1:
- transition from Medic project (coronary analysis app) to Echo project
- reuse code from Medic project if possible
- remove all unnecessary code and files from Medic project
- remove SAM2 support (keep only MedSAM2)


Some information:
- data type: 2D, M-Mode, Doppler, 3D, Strain.
- online viewer: https://www.dicomlibrary.com/meddream/?study=1.3.6.1.4.1.44316.6.102.1.20261023183452424.27478951279385216822
- example data inside `data` folder (DICOM files, anonymized)
- Python version: 3.14 (`.venv` is linking to uv venv)


old README.md below:

# Medic

- testowane na wersji Pythona 3.14.4
- wymagane biblioteki w `requirements.txt` + MedSAM2 (https://github.com/bowang-lab/MedSAM2)
- w tej chwili aplikacja spodziewa się checkpointów w katalogu `checkpoints` (`checkpoints/MedSAM2` i `checkpoints/SAM2`). Najlepiej zrobić linki symboliczne do katalogów z checkpointami. 
- uwaga: by używać oryginalnych modeli SAM2 (opcjonalne), nie instalujemy SAM2, lecz dogrywamy configi do MedSAM2.

