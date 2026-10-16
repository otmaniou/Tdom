import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import fixtures  # noqa: E402
from tlone import domvalid, nbrunner, planning, transfers  # noqa: E402
from tlone.config import load_settings  # noqa: E402
from tlone.montant_lettres import lettres_to_number  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TLONE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("TLONE_RUN_MODE", "local")
    p = fixtures.build(tmp_path)
    return p, load_settings()


# ------------------------------------------------------------ montant en lettres
@pytest.mark.parametrize("txt,val", [
    ("UN MILLION DEUX CENT SOIXANTE ET UN MILLE SIX CENTS DINARS ALGERIENS", 1261600),
    ("TROIS CENT DOUZE MILLE DEUX CENT CINQUANTE CINQ DINARS", 312255),
    ("CENT QUATRE VINGT MILLE DINARS", 180000),
    ("QUATRE-VINGT-DIX-NEUF MILLE NEUF CENT QUATRE-VINGT-DIX-NEUF DA", 99999),
    ("DEUX CENT MILLE DINARS ET 50 CTS", 200000.50),
    ("SOIXANTE DIX SEPT MILLE DINARS ALGÉRIENS ET QUARANTE CENTIMES", 77000.40),
    ("MILLE DINARS", 1000),
])
def test_lettres(txt, val):
    assert lettres_to_number(txt) == pytest.approx(val)


def test_lettres_illisible():
    assert lettres_to_number("TROIS CENT BLURP MILLE") is None


# ------------------------------------------------------------ runner
def test_patch_source_root_and_glob():
    src = "INPUT_DIR = Path('/mnt/data/domiciliations_in')\nMAX_PDFS = None\npdfs = sorted(INPUT_DIR.glob('*.pdf'))\n" \
          "assert RAW_JSON_DIR == Path('/mnt/data/x')\nMODEL_PATH = '/domino/edv/old'\n"
    out, applied = nbrunner.patch_source(src, "dom_extract", "/domino/datasets/local/tlone", 5, "/models/new")
    assert "/mnt/data" not in out and "/domino/datasets/local/tlone/domiciliations_in" in out
    assert "MAX_PDFS = 5" in out and "suffix.lower() == '.pdf'" in out
    assert 'MODEL_PATH = "/models/new"' in out
    assert any(a.startswith("DATA_ROOT") for a in applied)


def test_patch_default_root_untouched():
    src = "OUTPUT_ROOT = Path('/mnt/data/document_pipeline/V15_A')\n"
    out, applied = nbrunner.patch_source(src, "dom_post", "/mnt/data", None, None)
    assert out == src and applied == []


def test_real_notebooks_patchable():
    s = load_settings()
    for step, nb in s.notebooks.items():
        prepared, applied = nbrunner.prepare_notebook(nb, step, "/tmp/x", 3, None)
        assert any(a.startswith("DATA_ROOT") for a in applied), step
        code = "\n".join(c.source for c in prepared.cells if c.cell_type == "code")
        assert "/mnt/data" not in code
        if step in ("dom_extract", "ov_extract"):
            assert "GLOB_PDF_CASE_INSENSITIVE" in applied
        assert any(a.startswith(("MAX_", "pdfs[")) for a in applied), (step, applied)


# ------------------------------------------------------------ module 1
def test_domvalid_roundtrip(env):
    p, _ = env
    man = domvalid.load_manual(p.validation_xlsx)
    assert list(man["_ROW"]) == [2, 3, 4, 5]
    mt = p.validation_xlsx.stat().st_mtime
    ed = man.copy()
    ed.loc[ed["FICHIER"] == "CELIK_MEHMET_CNT.pdf", ["DECISION_MANUELLE", "VALEUR_VALIDEE"]] = ["CORRIGEE", ""]
    assert domvalid.check_decisions(ed)  # CORRIGEE sans valeur bloqué
    ed.loc[ed["FICHIER"] == "CELIK_MEHMET_CNT.pdf", "VALEUR_VALIDEE"] = "02700731010830000155"
    assert not domvalid.check_decisions(ed)
    res = domvalid.save_decisions(p.validation_xlsx, ed, expected_mtime=mt)
    assert len(res["changes"]) == 2 and Path(res["backup"]).exists()
    re = domvalid.load_manual(p.validation_xlsx)
    assert re.loc[re["FICHIER"] == "CELIK_MEHMET_CNT.pdf", "DECISION_MANUELLE"].iloc[0] == "CORRIGEE"
    # Les autres feuilles sont conservées
    assert "DOSSIERS_A_VALIDER" in domvalid.sheet_names(p.validation_xlsx)
    with pytest.raises(RuntimeError):
        domvalid.save_decisions(p.validation_xlsx, ed, expected_mtime=mt)  # fichier modifié entre-temps


def test_progress(env):
    p, _ = env
    pr = domvalid.progress(domvalid.load_manual(p.validation_xlsx)).set_index("FICHIER")
    assert pr.loc["DEMIR_ALI_CNT.pdf", "STATUT_VALIDATION"] == "REJETE"
    assert pr.loc["CELIK_MEHMET_CNT.pdf", "RESTANT"] == 1


# ------------------------------------------------------------ module 2
def _planning(p, excl=False):
    dos = domvalid.load_sheet(p.validation_xlsx, "DOSSIERS_A_VALIDER")
    man = domvalid.load_sheet(p.validation_xlsx, "A_VALIDER_MANUELLEMENT")
    pa = pd.read_excel(p.param_aug_xlsx, dtype=object)
    return planning.build_planning(dos, man, pa, exclure_validation_incomplete=excl)


def test_planning_rules(env):
    p, _ = env
    r = _planning(p)
    pl, rej = r["Planning_TL"], r["REJETS_PLANNING"].set_index("FICHIER")
    assert r["_dq"] == []
    assert rej.loc["DEMIR_ALI_CNT.pdf", "MOTIF"] == "REJETE_EN_PARTIE_2A"
    assert "COMPTE_FINAL_ABSENT" in rej.loc["CELIK_MEHMET_CNT.pdf", "MOTIF"]
    kaya = pl[pl["NOM_TRAVAILLEUR"] == "KAYA AHMET"]
    assert kaya["DOM_ID"].nunique() == 1  # contrat + augmentation sur la même DOM
    jan = kaya[kaya["MOIS_BASE"] == "2026-01"].iloc[0]
    assert jan["PERIODE_TL"] == "2026-01P2" and jan["NB_JOURS_SEGMENT"] == 29
    assert jan["MONTANT_MAX_THEORIQUE"] == round(312255 * 29 / 31, 2)
    mar = kaya[kaya["MOIS_BASE"] == "2026-03"].iloc[0]
    apr = kaya[kaya["MOIS_BASE"] == "2026-04"].iloc[0]
    assert mar["TYPE_VERSION"] == "NOUVEAU_CONTRAT" and mar["MONTANT_MAX_THEORIQUE"] == 312255
    assert apr["TYPE_VERSION"] == "AUGMENTATION" and apr["NUMERO_AUGMENTATION"] == 1
    assert apr["MONTANT_MAX_THEORIQUE"] == 332500
    last = kaya.iloc[-1]
    assert last["PERIODE_TL"] == "2028-01P1" and last["NB_JOURS_SEGMENT"] == 2


def test_planning_matches_notebook(env, monkeypatch):
    """Exécute le VRAI notebook Planning_TL_V15A sur le même jeu et compare."""
    p, _ = env
    import nbformat
    from nbclient import NotebookClient
    nb = nbformat.read(str(Path(__file__).resolve().parent.parent / "notebooks" / "Planning_TL_V15A.ipynb"), 4)
    for c in nb.cells:
        if c.cell_type == "code":
            c.source = c.source.replace("/mnt/data", str(p.data_root))
    NotebookClient(nb, timeout=120, kernel_name="python3").execute()
    ref = pd.read_csv(p.planning_csv, dtype=str).fillna("")
    mine = _planning(p)["Planning_TL"].astype(str).replace({"None": "", "nan": ""})
    ref = ref[mine.columns]
    for c in ("MONTANT_MAX_THEORIQUE", "COEFFICIENT_PRORATA", "PART_TRANSFERABLE_CTS"):
        assert (ref[c].astype(float).round(6) == mine[c].replace("", "nan").astype(float).round(6)).all(), c
    for c in ("PERIODE_ID", "DOM_ID", "VERSION_ID", "PERIODE_TL", "TYPE_VERSION", "DATE_DEBUT_SEGMENT"):
        assert list(ref[c]) == list(mine[c]), c


# ------------------------------------------------------------ module 3
def test_transfer_controls(env):
    p, s = env
    r = _planning(p)
    planning.export(r, p.planning_xlsx, p.planning_csv)
    pl = planning.load_planning(p.planning_csv)
    audit = transfers.read_audit_xlsx(transfers.latest_audit(p.tr_out)[0])
    assert len(audit) == 4 and "OV.montant_chiffres" in audit.columns
    atf = transfers.load_referential(p.atf_xlsx, transfers.ATF_COLUMNS)
    aut = transfers.load_referential(p.autorisations_xlsx, transfers.AUT_COLUMNS)
    reg = transfers.load_registre(p.registre_csv)
    sy, ch = transfers.run_controls(audit, pl, reg, atf, aut, s, today=date(2026, 4, 10))
    sy = sy.set_index("FICHIER")
    mar = sy.loc["07310-108259-202603.pdf"]
    assert mar["STATUT_CONTROLE"] == "CONFORME", ch[ch.FICHIER == "07310-108259-202603.pdf"].to_dict("records")
    assert mar["PERIODE_TL"] == "2026-03" and mar["PROVISION_ATLAS"] == 317255
    feb = sy.loc["07310-108259-202602.pdf"]
    assert feb["STATUT_CONTROLE"] == "NON_CONFORME" and "T09" in feb["MOTIFS"] and "T10" in feb["MOTIFS"]
    jan = sy.loc["07310-108259-202601P2.pdf"]
    assert jan["PERIODE_TL"] == "2026-01P2" and jan["STATUT_CONTROLE"] in ("A_REVOIR", "NON_CONFORME")
    demir = sy.loc["07310-108262-202605.pdf"]
    assert demir["STATUT_CONTROLE"] == "NON_CONFORME" and "T04" in demir["MOTIFS"]

    # Décision + registre + consommation
    ed = sy.reset_index()[["FICHIER", "AUDIT_SOURCE", "STATUT_CONTROLE", "PERIODE_ID"]].copy()
    ed["DECISION"], ed["COMMENTAIRE"] = "", ""
    ed.loc[ed.FICHIER == "07310-108259-202603.pdf", "DECISION"] = "VALIDE"
    ed.loc[ed.FICHIER == "07310-108262-202605.pdf", "DECISION"] = "VALIDE"
    assert transfers.check_decisions(ed)  # non rattaché ne peut être validé
    ed.loc[ed.FICHIER == "07310-108262-202605.pdf", "DECISION"] = "REJETE"
    ed.loc[ed.FICHIER == "07310-108262-202605.pdf", "COMMENTAIRE"] = "DOM rejetée"
    assert not transfers.check_decisions(ed)
    assert transfers.save_decisions(p.decisions_csv, ed, "testeur") == 2
    dec = transfers.load_decisions(p.decisions_csv)
    assert transfers.register(p.registre_csv, sy.reset_index(), dec, "testeur") == 1
    assert transfers.register(p.registre_csv, sy.reset_index(), dec, "testeur") == 0  # idempotent
    reg = transfers.load_registre(p.registre_csv)
    cons = transfers.consumption(pl, reg, today=date(2026, 4, 10)).set_index("PERIODE_TL")
    assert cons.loc["2026-03", "STATUT_PERIODE"] == "TRANSFERE"
    assert cons.loc["2026-02", "STATUT_PERIODE"] == "NON_TRANSFERE"
    # Un 2e OV sur mars est désormais bloqué (déjà transféré)
    sy2, ch2 = transfers.run_controls(audit.iloc[[0]].assign(fichier="BIS-202603.pdf"), pl, reg, atf, aut, s,
                                      today=date(2026, 4, 10))
    assert sy2.iloc[0]["STATUT_CONTROLE"] in ("NON_CONFORME",)


def test_periodes():
    assert transfers.parse_periode("MARS 2026 PART 1") == ("2026-03", "P1")
    assert transfers.parse_periode("FÉVRIER.2026") == ("2026-02", None)
    assert transfers.parse_periode("03/2026") == ("2026-03", None)
    assert transfers.periode_from_filename("02700731011155100123-202510P2.PDF") == ("2025-10", "P2")
    assert transfers.periode_from_filename("07310-108262-202605.pdf") == ("2026-05", None)


def test_carry_over(env):
    p, _ = env
    from tlone.common import backup
    prev = backup(p.validation_xlsx)
    # simulate a Part 2 rerun : decisions wiped
    man = domvalid.load_manual(p.validation_xlsx)
    wiped = man.copy()
    for c in domvalid.EDITABLE:
        wiped[c] = ""
    domvalid.save_decisions(p.validation_xlsx, wiped)
    todo = domvalid.carry_over(prev, p.validation_xlsx)
    assert len(todo) == 3  # 3 lignes décidées dans le jeu, la 4e était vide
    domvalid.save_decisions(p.validation_xlsx, todo)
    again = domvalid.load_manual(p.validation_xlsx)
    assert list(again["DECISION_MANUELLE"]) == list(man["DECISION_MANUELLE"])


def test_jobs_local_launch(env, monkeypatch):
    p, s = env
    from tlone import jobs
    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *a, **k: type("P", (), {"pid": 4242})())
    rec = jobs.launch(s, "dom_post", 3, "testeur")
    assert rec["backup_validation"] and Path(rec["backup_validation"]).exists()
    runs = jobs.list_runs(s)
    assert runs[0]["run_id"] == rec["run_id"] and runs[0]["status"] == "EN_FILE"
