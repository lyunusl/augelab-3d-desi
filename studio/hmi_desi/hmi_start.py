"""Start the exported scenario with the machine's installed Studio runtime."""

import os
import sys
from pathlib import Path


def main() -> None:
    package = Path(__file__).resolve().parent
    scene = package / "hmi_scenario.pmod"
    if not scene.is_file():
        raise SystemExit(f"HMI senaryosu bulunamadı: {scene}")

    os.environ.setdefault("AUGELAB_HMI_RUNTIME_DIR", str(package))
    studio_source = os.environ.get("AUGELAB_STUDIO_SOURCE")
    if studio_source:
        sys.path.insert(0, studio_source)

    try:
        from studio.view.main_window.forms.hmi.hmi_ui import start_hmi_ui
    except ModuleNotFoundError as error:
        if error.name != "studio":
            raise
        raise SystemExit("HMI için AugeLab Studio'nun kendi Python kurulumunu kullanın.") from error

    # Studio uses the target machine's own headless license or activation prompt.
    start_hmi_ui(str(scene), "")


if __name__ == "__main__":
    main()
