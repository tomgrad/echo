"""Key frame XML persistence: points and custom-mask outlines per object and frame."""
import xml.etree.ElementTree as ET


def write_keyframes(path, key_frames, key_frame_points, key_frame_outlines) -> None:
    root = ET.Element("keyframes")
    for frame_idx in key_frames:
        kf_el = ET.SubElement(root, "keyframe", index=str(frame_idx))
        for obj_id, frame_map in key_frame_points.items():
            for pt in frame_map.get(frame_idx, []):
                ET.SubElement(
                    kf_el, "point",
                    x=str(pt[0]), y=str(pt[1]),
                    positive=("true" if pt[2] else "false"),
                    obj_id=str(obj_id),
                )
        for obj_id, frame_map in key_frame_outlines.items():
            vertices = frame_map.get(frame_idx, [])
            if not vertices:
                continue
            outline_el = ET.SubElement(kf_el, "outline", obj_id=str(obj_id))
            for vertex in vertices:
                ET.SubElement(outline_el, "vertex", x=str(vertex[0]), y=str(vertex[1]))
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="unicode", xml_declaration=True)


def read_keyframes(path, frame_count: int = 0):
    """Return (key_frames, points, outlines). Raise ET.ParseError or ValueError if the file is bad."""
    root = ET.parse(path).getroot()
    key_frames = []
    key_frame_points = {}
    key_frame_outlines = {}
    try:
        if root.tag != "keyframes":
            raise ValueError("Not a valid key frames file.")
        for kf_el in root.findall("keyframe"):
            frame_idx = int(kf_el.get("index"))
            if frame_count and not 0 <= frame_idx < frame_count:
                raise ValueError(f"Key frame {frame_idx} is outside the loaded image ({frame_count} frames).")
            if frame_idx not in key_frames:
                key_frames.append(frame_idx)
            for outline_el in kf_el.findall("outline"):
                obj_id = int(outline_el.get("obj_id"))
                vertices = [
                    [int(vertex_el.get("x")), int(vertex_el.get("y"))]
                    for vertex_el in outline_el.findall("vertex")
                ]
                if vertices:
                    key_frame_outlines.setdefault(obj_id, {})[frame_idx] = vertices
            for pt_el in kf_el.findall("point"):
                x = pt_el.get("x")
                y = pt_el.get("y")
                positive = pt_el.get("positive")
                obj_id = pt_el.get("obj_id")
                if x is None or y is None or positive is None or obj_id is None:
                    raise ValueError(
                        "Invalid keyframe file: each point must include x, y, positive, and obj_id"
                    )
                key_frame_points.setdefault(int(obj_id), {}).setdefault(frame_idx, []).append([
                    int(x),
                    int(y),
                    positive == "true",
                ])
    except TypeError as exc:
        raise ValueError(str(exc)) from exc
    return sorted(key_frames), key_frame_points, key_frame_outlines
