from grit.steps.post_curation.finalize_qc import finalize_for_qc as finalize_for_qc
from grit.steps.post_curation.haplotig_files import run_haplotig_files as run_haplotig_files
from grit.steps.post_curation.hic_remapping import run_hic_remapping as run_hic_remapping
from grit.steps.post_curation.pretext_to_asm import run_pretext_to_asm as run_pretext_to_asm
from grit.steps.post_curation.qv import run_qv as run_qv
from grit.steps.post_curation.validate_files import run_validate_files as run_validate_files

validate_curated_files = run_validate_files
