# EMIC/IWYMIC Performance Signal Analysis

Generated 2026-07-23 from the reviewed 3,112-identity master roster.

## Question

Among named EMIC/IWYMIC award recipients, does stronger performance at the first observed stage contest predict later APMO/IMO participation and awards? This is a predictive association study, not a causal estimate of contest impact.

## Cohort And Outcomes

- Unit: one reviewed contestant identity.
- Baseline: earliest EMIC or IWYMIC award year and its percentile.
- Headline window: five calendar years after baseline.
- Five-year eligible samples: 1,754 for APMO and 2,486 for IMO.
- APMO baseline years begin in 2015 because complete contestant-level results begin in 2016.
- Award means Gold, Silver, Bronze, or Honourable Mention; medal excludes Honourable Mention.
- Same-year and earlier higher-contest results are never outcomes.

## Unadjusted Descriptive Signal

The unrestricted through-2026 rates increase across the observed baseline-percentile bands:

| Performance Band | Contestants | Later Apmo Award Percent | Later Imo Award Percent |
|---|---|---|---|
| 25-50% | 936 | 4.400 | 5.800 |
| 50-75% | 1136 | 9.400 | 10.000 |
| 75-100% | 1040 | 17.700 | 17.600 |

The result pages contain award recipients only, so there are no observations in the bottom quarter of the complete contestant field. The table cannot compare named winners with unnamed non-awardees.

## Out-Of-Time Predictive Models

The baseline ridge-logistic model uses country, stage, and baseline year. The performance model adds baseline percentile, a quadratic term, and a percentile-by-stage interaction. Each test cohort is predicted only from earlier baseline years.

| Destination | Outcome | Model | Predictions | Events | Average Precision | Roc Auc | Brier Score |
|---|---|---|---|---|---|---|---|
| APMO | award | Baseline | 879 | 82 | 0.278 | 0.767 | 0.076 |
| APMO | award | Performance | 879 | 82 | 0.365 | 0.838 | 0.071 |
| APMO | medal | Baseline | 879 | 59 | 0.221 | 0.767 | 0.058 |
| APMO | medal | Performance | 879 | 59 | 0.322 | 0.848 | 0.054 |
| IMO | award | Baseline | 1411 | 131 | 0.276 | 0.763 | 0.076 |
| IMO | award | Performance | 1411 | 131 | 0.351 | 0.809 | 0.072 |
| IMO | medal | Baseline | 1411 | 91 | 0.153 | 0.712 | 0.058 |
| IMO | medal | Performance | 1411 | 91 | 0.233 | 0.797 | 0.055 |

Incremental performance-model results (positive values favor adding baseline performance):

| Destination | Outcome | Delta Average Precision | Delta Average Precision Lower | Delta Average Precision Upper | Brier Improvement | Brier Improvement Lower | Brier Improvement Upper |
|---|---|---|---|---|---|---|---|
| APMO | award | 0.088 | 0.033 | 0.161 | 0.004 | 0.000 | 0.009 |
| APMO | medal | 0.101 | 0.034 | 0.189 | 0.004 | 0.001 | 0.007 |
| IMO | award | 0.075 | 0.018 | 0.145 | 0.004 | 0.000 | 0.009 |
| IMO | medal | 0.080 | 0.032 | 0.144 | 0.003 | -0.000 | 0.005 |

Country-cluster bootstrap intervals quantify uncertainty in the metric differences. Predictive lift should be judged jointly with calibration and not only by whether one interval crosses zero.

## Figures

1. `Figures/01 Performance Signal Curves.png`: raw quintile rates and country/year-adjusted curves.
2. `Figures/02 Outcome Transitions.png`: baseline award tiers to five-year outcome classes.
3. `Figures/03 Cumulative Award Incidence.png`: time to first later award with right-censoring.
4. `Figures/04 Country Progression Rates.png`: five-year country estimates with Wilson intervals.
5. `Figures/05 Model Comparison and Calibration.png`: out-of-time lift and calibration.
6. `Figures/06 Cohort Coverage.png`: cohort size and follow-up availability.

## Interpretation Rules

- A rising curve is evidence of association among EMIC/IWYMIC award recipients.
- Improvement over the baseline model means performance adds predictive information beyond measured country, year, and stage variables.
- A persistent association is not evidence that EMIC/IWYMIC participation caused later success.
- Participation and conditional performance are separate processes; never encode a nonparticipant as having zero percentile.

## Limitations

- Non-awarded EMIC/IWYMIC contestants are unnamed and cannot be followed.
- Country selection systems, training access, age, and prior preparation are unmeasured confounders.
- IWYMIC total-participant denominators are estimated, so medal-tier analyses are an important sensitivity check.
- The official APMO 2026 score-level report is complete but still marked preliminary; refresh the pipeline when the source becomes final.
- Recent cohorts are right-censored; fixed-window models intentionally exclude cohorts without complete follow-up.
- APMO 2013-2015 lacks complete contestant-level result tables and is excluded from complete-window outcomes.

## Reproduction

```powershell
python "2 Processing Scripts/analyze_performance_signal.py"
```
