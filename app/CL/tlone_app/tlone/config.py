"""Configuration centrale TL-One.

Tous les chemins dérivent de TLONE_DATA_ROOT (défaut : /mnt/data, identique aux
notebooks validés). Rien n'est codé en dur ailleurs dans l'application.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_VERSION = "TLONE_APP_V1.0"

APP_DIR = Path(__file__).resolve().parent.parent
NOTEBOOK_DIR = APP_DIR / "notebooks"


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
        for d in (self.dom_in, self.post_root, self.planning_dir, self.tr_in,
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
        return {
            "tier": _env(f"TLONE_{up}_TIER", default_tier),
            "environment": _env(f"TLONE_{up}_ENV", ""),
            "python": _env(f"TLONE_{up}_PYTHON", ""),
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
        notebooks={
            "dom_extract": NOTEBOOK_DIR / "pipeline_part1_v15_A_fast_standardized_qwen3_8_27b.ipynb",
            "dom_post": NOTEBOOK_DIR / "pipeline_part2_v15_A_normalization_dq_confidence.ipynb",
            "ov_extract": NOTEBOOK_DIR / "pipeline_ocr_vlm_v26_stabilise_internvl_note.ipynb",
        },
    )


STEPS = {
    "dom_extract": {"label": "DOM — Extraction VLM (Partie 1, GPU)", "gpu": True},
    "dom_post": {"label": "DOM — Normalisation / DQ / Carthago (Partie 2, CPU)", "gpu": False},
    "ov_extract": {"label": "OV — Extraction VLM transferts (v26, GPU)", "gpu": True},
}
