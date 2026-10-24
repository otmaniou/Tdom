"""Verifie une copie de l'app faite par copier-coller (GitHub -> Notepad++ -> Domino).

Le copier-coller change les fins de ligne (CRLF), peut ajouter un BOM, des espaces en fin de
ligne ou supprimer la derniere ligne vide : md5sum -c MANIFEST.md5 echoue alors meme si le code
est le bon. Ce script compare le contenu NORMALISE de chaque fichier a MANIFEST_NORM.txt.

  python3 verifier_copie.py            # verifier
  python3 verifier_copie.py --reparer  # remettre les fins de ligne Unix (LF), puis verifier

--reparer ne change que la forme (fins de ligne, BOM, espaces en fin de ligne) : jamais le code.
Il est necessaire pour les scripts .sh (bash refuse les CRLF).
"""
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
MANIFEST = ROOT / "MANIFEST_NORM.txt"


def normaliser(b: bytes) -> bytes:
    if b.startswith(b"\xef\xbb\xbf"):
        b = b[3:]
    lignes = b.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
    return b"\n".join(l.rstrip(b" \t") for l in lignes).rstrip(b"\n") + b"\n"


def forme_unix(b: bytes) -> bytes:
    """Fins de ligne LF, sans BOM ni espaces en fin de ligne ; la fin du fichier est gardee telle quelle."""
    if b.startswith(b"\xef\xbb\xbf"):
        b = b[3:]
    return b"\n".join(l.rstrip(b" \t") for l in b.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n"))


def empreinte(b: bytes) -> str:
    return hashlib.md5(normaliser(b)).hexdigest()


def main() -> int:
    reparer = "--reparer" in sys.argv
    if not MANIFEST.exists():
        print("MANIFEST_NORM.txt absent : le copier a cote de ce script.")
        return 2
    attendu = {}
    for ligne in MANIFEST.read_text(encoding="utf-8", errors="replace").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#"):
            h, f = ligne.split(None, 1)
            attendu[f.strip()] = h
    ok, ko = 0, []
    for f, h in attendu.items():
        p = ROOT / f
        if not p.exists():
            ko.append(("ABSENT", f))
            continue
        b = p.read_bytes()
        if reparer and b"\x00" not in b:
            n = forme_unix(b)
            if n != b:
                p.write_bytes(n)
                print("repare   ", f)
            b = n
        if empreinte(b) == h:
            ok += 1
        else:
            ko.append(("DIFFERENT", f))
    for etat, f in ko:
        print(f"{etat:9} {f}")
    print(f"--- {ok}/{len(attendu)} fichiers identiques a la version livree")
    if ko:
        print("DIFFERENT = autre version ou ligne perdue au copier-coller : recopier ce fichier.")
    return 0 if not ko else 1


if __name__ == "__main__":
    sys.exit(main())
