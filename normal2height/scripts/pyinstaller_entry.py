"""PyInstaller entry point.

PyInstaller runs its target script standalone with no package context, so
src/normal2height/__main__.py's relative import (`from .cli import main`)
fails when pointed at directly. This wrapper does an absolute import instead
(with `src/` on sys.path via --paths, see build_executable.sh) so the
resulting binary can find the package normally.
"""
from normal2height.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
