# Echocardiography DICOM viewer

Goal: create a DICOM viewer for echocardiography recordings.
Tools: Python (pydicom, pyqtgraph, PySide6), GUI created as *.ui file (editable with QtDesigner)
Follow the design rules of this example: https://www.dicomlibrary.com/meddream/?study=1.3.6.1.4.1.44316.6.102.1.20261023183452424.27478951279385216822

Example DICOM recordings at 'data' directory (linked in this project's root dir)

# Relation to the 'Echo' project
- This viewer will be a subproject inside this Echo/MedSAM project. 
- In the future both projects might be merged. But for now this viewer will have it's own GUI.
- If it will make the development easier, it is allowed to reuse some parts of the Echo project.
- It is also allowed to refactor some of the code and modify the original Echo project, without changing it's GUI.

# MVP
- Import session folder from disk
- display thumbnails on the left panel
- display a number of selected recordings (eg. 2x2) in the main area.
