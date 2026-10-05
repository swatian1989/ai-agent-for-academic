# Study notes — Multimodal AI for drought-stress prediction in wheat

## Aim
Predict drought stress in bread wheat (Triticum aestivum) 7 days before visible symptoms by fusing
UAV RGB imagery, canopy temperature and 2,000 SNP markers.

## Setup
- Field trial, Faisalabad, Pakistan, 2024–25 season.
- 120 genotypes × 2 water regimes (well-watered vs. drought from booting stage) × 3 replicates = 720 plots.
- UAV flights every 5 days (RGB + thermal); soil moisture sensors; SNP genotyping (2,000 markers).
- Ground truth: leaf relative water content (RWC) and visual stress score.

## Models compared
- RGB-only CNN (ResNet-18)
- Thermal + weather gradient boosting
- Genomic-only GBLUP
- **Proposed**: late-fusion model (CNN embedding + thermal features + genomic PCs) with gradient boosting

## Key results
- Proposed fusion model: accuracy 91.3%, F1 0.90, AUC 0.95 (5-fold CV, genotype-grouped folds).
- RGB-only: accuracy 84.1%; thermal+weather: 86.7%; genomic-only: 71.2%.
- Fusion detected stress on average 6.4 days before visible symptoms (vs 3.1 days RGB-only).
- SHAP: canopy temperature depression and two SNP clusters on chromosomes 2B and 5A were the most important features.
- Model trained on 2024 data generalised to 2025 with accuracy 87.9%.

## Limitations noted by the team
- Single location; two seasons.
- Genotyping cost limits deployment for smallholders.
- Thermal imagery sensitive to time of day.

## References we want to cite (authors' own list)
- Khan A, Ali B (2023). Deep learning for drought stress detection in wheat using RGB imagery. Computers and Electronics in Agriculture.
- Zhang C (2022). Hyperspectral indices for early drought detection in cereals: a review. Remote Sensing.
- Rehman D, Fatima E (2024). Genomic prediction of drought tolerance in wheat landraces. Theoretical and Applied Genetics.
