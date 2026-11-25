import json
import os
from pathlib import Path

from echo_viewer.session import RecordingInfo

FILE_NAME = "descriptions.json"


class Descriptions:
    """One-line recording descriptions stored in the session folder."""

    def __init__(self, folder: Path, data: dict[str, str], warning: str | None = None):
        self._folder = folder
        self._data = data
        self.warning = warning

    @classmethod
    def load(cls, folder: Path) -> "Descriptions":
        path = folder / FILE_NAME
        if not path.exists():
            return cls(folder, {})
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("expected a JSON object")
            data = {str(k): str(v) for k, v in raw.items()}
        except (OSError, ValueError) as exc:
            return cls(folder, {}, f"Cannot read {FILE_NAME}: {exc}")
        return cls(folder, data)

    def _key(self, info: RecordingInfo) -> str:
        if info.sop_instance_uid:
            return info.sop_instance_uid
        try:
            return info.path.relative_to(self._folder).as_posix()
        except ValueError:
            return info.path.as_posix()

    def get(self, info: RecordingInfo) -> str:
        return self._data.get(self._key(info), "")

    def set(self, info: RecordingInfo, text: str) -> None:
        text = " ".join(text.split())
        key = self._key(info)
        if text:
            self._data[key] = text
        else:
            self._data.pop(key, None)
        self._save()

    def _save(self) -> None:
        path = self._folder / FILE_NAME
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
