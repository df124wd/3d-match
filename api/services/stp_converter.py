import os
import logging
import tempfile

logger = logging.getLogger(__name__)


def is_step_file(file_path: str) -> bool:
    ext = os.path.splitext(file_path)[1].lower()
    return ext in (".stp", ".step")


def is_stl_file(file_path: str) -> bool:
    ext = os.path.splitext(file_path)[1].lower()
    return ext == ".stl"


def step_to_stl(step_path: str, output_path: str = None) -> str:
    if output_path is None:
        tmp_dir = tempfile.gettempdir()
        base_name = os.path.splitext(os.path.basename(step_path))[0]
        output_path = os.path.join(tmp_dir, f"{base_name}_converted.stl")

    try:
        return _convert_with_pythonocc(step_path, output_path)
    except ImportError:
        logger.warning("pythonOCC not available, trying FreeCAD fallback")

    return _convert_with_freecad(step_path, output_path)


def _convert_with_pythonocc(step_path: str, output_path: str) -> str:
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.StlAPI import StlAPI_Writer
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh

    reader = STEPControl_Reader()
    status = reader.ReadFile(step_path)
    if status != 1:
        raise ValueError(f"Failed to read STEP file: {step_path}")

    reader.TransferRoots()
    shape = reader.OneShape()

    mesh = BRepMesh_IncrementalMesh(shape, 0.1)
    mesh.Perform()

    writer = StlAPI_Writer()
    writer.Write(shape, output_path)

    logger.info("Converted STEP -> STL via pythonOCC: %s", output_path)
    return output_path


def _convert_with_freecad(step_path: str, output_path: str) -> str:
    import subprocess

    step_path_escaped = step_path.replace("\\", "/")
    output_path_escaped = output_path.replace("\\", "/")

    macro = f"""
import FreeCAD
import Mesh
doc = FreeCAD.open("{step_path_escaped}")
__objs__ = []
for obj in doc.Objects:
    if hasattr(obj, 'Shape'):
        __objs__.append(obj)
Mesh.export(__objs__, "{output_path_escaped}")
FreeCAD.closeDocument(doc.Name)
"""
    macro_path = step_path + "_convert_macro.py"
    with open(macro_path, "w") as f:
        f.write(macro)

    try:
        result = subprocess.run(
            ["freecadcmd", "-c", macro_path],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"FreeCAD conversion failed: {result.stderr}")
    finally:
        if os.path.exists(macro_path):
            os.remove(macro_path)

    logger.info("Converted STEP -> STL via FreeCAD: %s", output_path)
    return output_path
