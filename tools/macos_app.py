"""DESN-SW-013: 同じPython GUIをmacOSの識別可能な.appとして起動する。

CPython埋込みの公式APIを使う薄い起動入口。CAN/GUI本体はhost.mainのまま。
参照: https://docs.python.org/3.14/extending/embedding.html
生成物はプロジェクト内.toolsへ置き、システムPythonを変更しない。
"""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import sysconfig


# DESN-SW-013
def build(arguments):
    root = Path(__file__).resolve().parent.parent
    bundle = root / ".tools" / "Pico CAN.app"
    contents = bundle / "Contents"
    resources = contents / "Resources"
    binary = contents / "MacOS" / "PicoCAN"
    resources.mkdir(parents=True, exist_ok=True)
    binary.parent.mkdir(parents=True, exist_ok=True)
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "jp.local.pico-spi-canfd",
        "CFBundleName": "Pico CAN", "CFBundleDisplayName": "Pico CAN",
        "CFBundleExecutable": "PicoCAN", "CFBundlePackageType": "APPL",
        "CFBundleVersion": "0.1.0", "NSHighResolutionCapable": True,
    }))
    (resources / "arguments.json").write_text(json.dumps(arguments))
    bootstrap = resources / "launch.py"
    bootstrap.write_text(
        '"""DESN-SW-013: 設定引数を読み、通常のGUI入口を実行する。"""\n'
        "import json, os, runpy, sys\nfrom pathlib import Path\n"
        f"os.chdir({str(root)!r})\nsys.path.insert(0, {str(root)!r})\n"
        "sys.argv = ['pico-can'] + json.loads(Path(__file__).with_name('arguments.json').read_text())\n"
        "runpy.run_module('host.main', run_name='__main__')\n"
    )
    source = resources / "launcher.c"
    source.write_text(
        '/* DESN-SW-013: Appの識別を維持したまま、既存CPythonを呼び出す。 */\n'
        '#include <Python.h>\nint main(void) {\n'
        f'  char *args[] = {{{json.dumps(sys.executable)}, {json.dumps(str(bootstrap))}, NULL}};\n'
        '  return Py_BytesMain(2, args);\n}\n'
    )
    library = sysconfig.get_config_var("LIBDIR")
    subprocess.run(["clang", str(source), "-I" + sysconfig.get_path("include"),
                    "-L" + library, "-lpython3.14", "-Wl,-rpath," + library,
                    "-o", str(binary)], check=True)
    # 配布Pythonのinstall nameが相対パスでも、Finder起動で解決できるよう固定する。
    dylib = (Path(library) / "libpython3.14.dylib").resolve()
    linked = subprocess.check_output(["otool", "-L", str(binary)], text=True)
    for line in linked.splitlines()[1:]:
        dependency = line.strip().split(" (", 1)[0]
        if Path(dependency).name == dylib.name:
            subprocess.run(["install_name_tool", "-change", dependency, str(dylib),
                            str(binary)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(binary)], check=True)
    return bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args().arguments
    print(build(args[1:] if args[:1] == ["--"] else args))
