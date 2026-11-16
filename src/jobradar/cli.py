"""Punto de entrada de la línea de comandos (se irá ampliando por fases)."""
import argparse

from jobradar import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobradar", description="Radar de convocatorias cortas")
    parser.add_argument("--version", action="version", version=f"jobradar {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
