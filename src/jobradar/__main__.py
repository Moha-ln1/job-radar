"""Permite `python -m jobradar ...` y `pythonw -m jobradar run`."""
import sys

from jobradar.cli import main

sys.exit(main())
