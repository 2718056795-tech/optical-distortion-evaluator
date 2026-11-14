"""Copy the upstream license files for the portable Windows package."""
from importlib import metadata
from pathlib import Path
import shutil
import sys

dependencies = (
    "altgraph", "certifi", "charset-normalizer", "contourpy", "cycler",
    "fonttools", "importlib_resources", "Jinja2", "kiwisolver", "MarkupSafe",
    "matplotlib", "numpy", "openpyxl", "packaging", "Pillow", "pyinstaller",
    "pyinstaller-hooks-contrib", "pyparsing", "python-dateutil", "PyYAML",
    "setuptools", "six", "zipp",
)

output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", output / "Python-LICENSE.txt")

license_names = ("license", "notice", "copying")
for name in dependencies:
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        continue
    for record in distribution.files or ():
        if record.name.lower().startswith(license_names):
            source = distribution.locate_file(record)
            if source.is_file():
                location = record.as_posix().replace("/", "-")
                shutil.copy2(source, output / f"{name}-{location}")
