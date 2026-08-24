"""Setzt die Empfängeradresse des Kontaktformulars vor dem Deploy ein.

Die Adresse gehört nicht in ein öffentliches Repository. `mail-to.inc` wird
deshalb mit einem leeren Platzhalter eingecheckt und erst im Deploy-Job aus
dem GitHub-Secret CONTACT_MAIL_TO befüllt. Der FTP-Mirror lädt nur getrackte
Dateien hoch, die Datei muss also existieren, bevor sie befüllt wird.
"""

from __future__ import annotations

import os
import pathlib
import sys

PLACEHOLDER = "return '';"
TARGET = pathlib.Path(__file__).resolve().parent.parent / "mail-to.inc"


def main() -> int:
    address = os.environ.get("CONTACT_MAIL_TO", "").strip()
    if not address:
        print("CONTACT_MAIL_TO ist nicht gesetzt", file=sys.stderr)
        return 1
    if "@" not in address or "\n" in address:
        print("CONTACT_MAIL_TO sieht nicht wie eine E-Mail-Adresse aus", file=sys.stderr)
        return 1

    body = TARGET.read_text(encoding="utf-8")
    if PLACEHOLDER not in body:
        print(f"Platzhalter {PLACEHOLDER!r} fehlt in {TARGET.name}", file=sys.stderr)
        return 1

    escaped = address.replace("\\", "\\\\").replace("'", "\\'")
    TARGET.write_text(body.replace(PLACEHOLDER, f"return '{escaped}';"), encoding="utf-8")
    print(f"Kontaktadresse eingesetzt ({len(address)} Zeichen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
