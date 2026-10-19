"""Configuration centrale TL-One.

Tous les chemins dérivent de TLONE_DATA_ROOT (défaut : /mnt/data, identique aux
notebooks validés). Rien n'est codé en dur ailleurs dans l'application.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP_VERSION = "TLONE_APP_V1.0"

APP_DIR = Path(__file__).resolve().parent.parent
NOTEBOOK_DIR = APP_DIR / "notebooks"


def _default_python(conda_env: str) -> str:
    """Interpréteur de l'environnement conda de l'image s'il existe (sinon : python courant)."""
    p = Path(f"/opt/conda/envs/{conda_env}/bin/python")
    return str(p) if p.exists() else sys.executable


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass(frozen=True)
class Paths:
    data_root: Path

    # ---------- Module 1 : domiciliations ----------
    @property
    def dom_in(self) -> Path:
        return self.data_root / "domiciliations_in"

    @property
    def v15_root(self) -> Path:
        return self.data_root / "document_pipeline" / "V15_A"

    @property
    def raw_json_dir(self) -> Path:
        return self.v15_root / "01_extraction_raw" / "json_dossiers"

    @property
    def post_root(self) -> Path:
        return self.v15_root / "02_postprocessing"

    @property
    def validation_xlsx(self) -> Path:
        return self.post_root / "validation_domiciliations_V15_A.xlsx"

    @property
    def fields_csv(self) -> Path:  # CHAMPS_DETAIL de la Partie 2 (toutes les valeurs lues, page, confiance)
        return self.post_root / "champs_detail_v13_8_3.csv"

    @property
    def dossiers_csv(self) -> Path:
        return self.post_root / "dossiers_a_valider_v13_8_3.csv"

    @property
    def carthago_match_csv(self) -> Path:
        return self.post_root / "carthago_domiciliation_match_v13_8_3.csv"

    @property
    def dom_app_dir(self) -> Path:  # décisions saisies dans l'app (jamais écrasées par la Partie 2)
        return self.v15_root / "02b_validation_app"

    @property
    def dom_journal(self) -> Path:
        return self.dom_app_dir / "journal_validation_dom.jsonl"

    @property
    def sources_reference_xlsx(self) -> Path:
        return self.referentiels_dir / "sources_reference_dom.xlsx"

    @property
    def carthago_xlsx(self) -> Path:
        return self.data_root / "Dossier de domiciliation.xlsx"

    @property
    def param_aug_xlsx(self) -> Path:
        return self.data_root / "parametres_augmentation.xlsx"

    # ---------- Module 2 : planning ----------
    @property
    def planning_dir(self) -> Path:
        return self.v15_root / "03_planning_tl"

    @property
    def planning_xlsx(self) -> Path:
        return self.planning_dir / "Planning_TL_V15A_REBUILD.xlsx"

    @property
    def planning_csv(self) -> Path:
        return self.planning_dir / "Planning_TL_V15A_REBUILD.csv"

    # ---------- Module 3 : transferts ----------
    @property
    def tr_in(self) -> Path:
        return self.data_root / "transferts_in"

    @property
    def tr_out(self) -> Path:
        return self.data_root / "transferts_out"

    @property
    def tr_root(self) -> Path:
        return self.v15_root / "04_transferts"

    @property
    def registre_csv(self) -> Path:
        return self.tr_root / "registre_transferts.csv"

    @property
    def decisions_csv(self) -> Path:
        return self.tr_root / "decisions_transferts.csv"

    @property
    def referentiels_dir(self) -> Path:
        return self.data_root / "referentiels"

    @property
    def vigilance_dir(self) -> Path:
        return self.tr_root / "vigilance"

    @property
    def vigilance_template(self) -> Path:  # modèle BNP « CHECK LIST TRANSFERT LIBRE » (avant vigilance)
        return self.referentiels_dir / "modele_avant_vigilance.xlsx"

    @property
    def atf_xlsx(self) -> Path:
        return self.referentiels_dir / "ATF.xlsx"

    @property
    def autorisations_xlsx(self) -> Path:
        return self.referentiels_dir / "AUTORISATIONS.xlsx"

    # ---------- Exécutions / audit ----------
    @property
    def runs_dir(self) -> Path:
        return self.data_root / "document_pipeline" / "runs"

    @property
    def audit_log(self) -> Path:
        return self.data_root / "document_pipeline" / "audit_tlone.jsonl"

    def ensure(self) -> None:
        for d in (self.dom_in, self.post_root, self.dom_app_dir, self.planning_dir, self.tr_in,
                  self.tr_out, self.tr_root, self.referentiels_dir, self.runs_dir):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass


@dataclass(frozen=True)
class Settings:
    paths: Paths
    # local = subprocess sur la machine de l'app (dev, vast.ai) ; domino = Domino Jobs
    run_mode: str
    gpu_hardware_tier: str
    cpu_hardware_tier: str
    model_dom: str
    model_ov: str
    # commande de lancement d'un job, relative à la racine du projet Domino
    job_cmd_prefix: str
    # Règles paramétrables (REG-05 / REG-06) — à confirmer métier (Q-01)
    plafond_pct_net: float = 0.95
    provision_majoration_dzd: float = 5000.0
    autorisation_validite_jours: int = 45
    # Vigilance : « Lieu de travail » de la check-list (raison sociale de l'employeur) et format des individus
    employeur_raison_sociale: str = "TOSYALI IRON STEEL INDUSTRY ALGERIE"
    vigilance_individus: str = "entier"
    tolerance_montant_dzd: float = 1.0
    seuil_similarite_nom: float = 0.80
    notebooks: dict = field(default_factory=dict)

    def step_runtime(self, step: str) -> dict:
        """Tier / environnement Domino / interpréteur Python propres à une étape.

        TLONE_<ETAPE>_TIER, TLONE_<ETAPE>_ENV, TLONE_<ETAPE>_PYTHON (ex. TLONE_OV_EXTRACT_ENV)
        priment sur les valeurs communes TLONE_GPU_TIER / TLONE_CPU_TIER.
        """
        up = step.upper()
        default_tier = self.gpu_hardware_tier if STEPS[step]["gpu"] else self.cpu_hardware_tier
        # Par défaut : Partie 1 -> tlone-tf5 (transformers 5) ; Partie 2 et v26 -> tlone-tf4 (4.57).
        conda_env = "tlone-tf5" if step == "dom_extract" else "tlone-tf4"
        return {
            "tier": _env(f"TLONE_{up}_TIER", default_tier),
            "environment": _env(f"TLONE_{up}_ENV", _env("TLONE_ENV_ID", "")),
            "python": _env(f"TLONE_{up}_PYTHON", _default_python(conda_env)),
            "model": {"dom_extract": self.model_dom, "ov_extract": self.model_ov}.get(step, ""),
        }


def load_settings() -> Settings:
    paths = Paths(Path(_env("TLONE_DATA_ROOT", "/mnt/data")))
    run_mode = _env("TLONE_RUN_MODE", "domino" if os.environ.get("DOMINO_PROJECT_ID") else "local")
    return Settings(
        paths=paths,
        run_mode=run_mode,
        gpu_hardware_tier=_env("TLONE_GPU_TIER", ""),
        cpu_hardware_tier=_env("TLONE_CPU_TIER", ""),
        model_dom=_env("TLONE_MODEL_DOM", ""),
        model_ov=_env("TLONE_MODEL_OV", ""),
        # Par défaut : le run_step.py du dossier d'où tourne l'app -> chaque version lance ses propres jobs
        job_cmd_prefix=_env("TLONE_JOB_CMD", f"python {APP_DIR / 'run_step.py'}"),
        plafond_pct_net=float(_env("TLONE_PLAFOND_PCT_NET", "0.95")),
        provision_majoration_dzd=float(_env("TLONE_PROVISION_MAJORATION", "5000")),
        autorisation_validite_jours=int(_env("TLONE_AUTORISATION_JOURS", "45")),
        employeur_raison_sociale=_env("TLONE_EMPLOYEUR_RAISON_SOCIALE", "TOSYALI IRON STEEL INDUSTRY ALGERIE"),
        vigilance_individus=_env("TLONE_VIGILANCE_INDIVIDUS", "entier"),
        notebooks={
            "dom_extract": NOTEBOOK_DIR / "pipeline_part1_v15_A_fast_standardized_qwen3_8_27b.ipynb",
            "dom_post": NOTEBOOK_DIR / "pipeline_part2_v15_A_normalization_dq_confidence.ipynb",
            # v27 par défaut ; TLONE_OV_NOTEBOOK=pipeline_ocr_vlm_v26_stabilise_internvl_note.ipynb pour revenir en v26
            "ov_extract": NOTEBOOK_DIR / _env("TLONE_OV_NOTEBOOK", "pipeline_ocr_vl27.ipynb"),
        },
    )


STEPS = {
    "dom_extract": {"label": "DOM — Extraction VLM (Partie 1, GPU)", "gpu": True},
    "dom_post": {"label": "DOM — Normalisation / DQ / Carthago (Partie 2, CPU)", "gpu": False},
    "ov_extract": {"label": "OV — Extraction VLM transferts (v27, GPU)", "gpu": True},
}
