# RealEstate360+ Owner-Labeled Maintenance Evaluation

## 1. Chapter 3 Methodology Paragraph

For the preliminary evaluation of the maintenance analytics components, the researchers used a completed owner-reviewed workbook containing 197 existing maintenance-request records exported from the RealEstate360+ dataset. The company owner served as the single qualified reviewer because the owner is familiar with the company?s maintenance operations and actual issue handling. The reviewer assigned a reference issue category (`PLUMBING`, `ELECTRICAL`, `STRUCTURAL`, or `OTHER`) and a reference priority level (`LOW`, `MEDIUM`, or `HIGH`) before any comparison with system predictions was performed. After validation, the normalized labels were compared against the deployed production logic only: the rule-based category detector was executed using `classify_issue_category(f"{title} {description}")`, while the maintenance-priority classifier was executed using `predict_priority(description)`, matching the existing request-submission workflow in `maintenance/views.py`. Because only one reviewer was involved, inter-rater agreement was not measured. The results therefore apply only to the 197 evaluated records and should be interpreted as preliminary implementation-level evidence rather than a general benchmark of maintenance-language performance across other datasets or users.

## 2. Chapter 4 Category Evaluation Results Table

| Metric | Value |
| --- | ---: |
| Total evaluated records | 197 |
| Correct predictions | 164 |
| Incorrect predictions | 33 |
| Overall accuracy | 0.8325 |
| Macro precision | 0.8605 |
| Macro recall | 0.8641 |
| Macro F1-score | 0.8358 |
| Keyword match coverage | 0.8274 |
| Unmatched rate | 0.1726 |
| Predicted as OTHER (count) | 34 |
| Predicted as OTHER (%) | 17.2589 |

| Category | Support | Precision | Recall | F1-score |
| --- | ---: | ---: | ---: | ---: |
| PLUMBING | 48 | 0.7586 | 0.9167 | 0.8302 |
| ELECTRICAL | 45 | 1.0000 | 1.0000 | 1.0000 |
| STRUCTURAL | 41 | 0.6833 | 1.0000 | 0.8119 |
| OTHER | 63 | 1.0000 | 0.5397 | 0.7010 |

## 3. Chapter 4 Category Confusion Matrix

| Human \ Predicted | PLUMBING | ELECTRICAL | STRUCTURAL | OTHER |
| --- | ---: | ---: | ---: | ---: |
| PLUMBING | 44 | 0 | 4 | 0 |
| ELECTRICAL | 0 | 45 | 0 | 0 |
| STRUCTURAL | 0 | 0 | 41 | 0 |
| OTHER | 14 | 0 | 15 | 34 |

## 4. Chapter 4 Category Interpretation

The owner-labeled category evaluation showed that the implemented rule-based detector achieved an overall accuracy of 83.25% across 197 maintenance records. The strongest result appeared in `ELECTRICAL`, where precision, recall, and F1-score were all 1.0000, indicating that the deployed keyword rules aligned closely with the owner?s reference labels for electrical concerns in this dataset. `PLUMBING` and `STRUCTURAL` also performed well in recall, but their precision values were lower because many owner-labeled `OTHER` cases were reassigned by the detector into those two keyword-driven categories. This is most visible in the confusion matrix, where 14 `OTHER` cases were predicted as `PLUMBING` and 15 `OTHER` cases were predicted as `STRUCTURAL`.

The main weakness of the category detector is therefore not basic recognition of clear plumbing, electrical, or structural issues, but handling ambiguous or nonstandard requests that the owner considered `OTHER`. The detector matched at least one keyword in 82.74% of the cases, while 17.26% remained unmatched and defaulted to the fallback output. Because the detector depends on an English keyword vocabulary, it remains limited by spelling variations, Tagalog or Taglish wording, requests containing multiple concerns, fallback behavior when no keyword matches, and tie-breaking behavior when several categories receive similar keyword hits. These results should be presented as preliminary evidence that the implemented rule-based detector can support maintenance triage, but not as proof of full reliability across broader maintenance-language conditions.

## 5. Chapter 4 Priority Evaluation Update

The separate owner-labeled evaluation of the deployed maintenance-priority classifier produced substantially weaker results than the category detector. Using the same production workflow implemented in `maintenance/views.py`, where only the maintenance description is passed to `predict_priority(description)`, the classifier achieved an overall accuracy of 32.49% across the same 197 records. Macro precision was 0.3239, macro recall was 0.3636, and macro F1-score was 0.2847. Per-class results were also modest: `LOW` obtained precision 0.0656, recall 0.4444, and F1-score 0.1143; `MEDIUM` obtained precision 0.3636, recall 0.3500, and F1-score 0.3567; and `HIGH` obtained precision 0.5424, recall 0.2963, and F1-score 0.3832.

The confusion matrix indicates that the model often underestimates or redistributes owner-labeled urgent concerns, especially from `HIGH` into `MEDIUM` and `LOW`. The most frequent priority errors were `HIGH -> MEDIUM` (48 cases), `MEDIUM -> LOW` (29 cases), and `HIGH -> LOW` (28 cases). Based on these results, the deployed priority classifier should be described as a decision-support aid only and not as a reliable standalone basis for maintenance urgency decisions. The owner-labeled evaluation is methodologically compatible with the deployed classifier because it uses the same production input flow, but the results do not support strong claims of predictive accuracy.

## 6. Abstract Revision

The study also included a preliminary owner-labeled evaluation of the maintenance analytics features using 197 existing maintenance-request records. For issue categorization, the deployed rule-based detector achieved 83.25% accuracy when compared with labels assigned by the company owner before system predictions were reviewed. However, the separate maintenance-priority classifier achieved only 32.49% accuracy on the same evaluated records, indicating that the current priority model should be treated as a decision-support component rather than an automated decision mechanism. These findings show that the implemented analytics are integrated into the system, but their performance varies by task and remains subject to operational limitations.

## 7. Scope and Delimitations Revision

The maintenance-category evaluation in this study was limited to 197 existing maintenance-request records reviewed by a single qualified respondent, namely the company owner. Because only one reviewer was involved, inter-rater agreement was not measured. The owner labels were completed before comparison with the system outputs, but the findings apply only to the evaluated records and do not establish general performance across all possible maintenance-language inputs. In addition, the rule-based category detector is limited by its English keyword vocabulary, spelling variations, Tagalog or Taglish text, requests containing multiple concerns, fallback behavior, and tie-breaking rules. The maintenance-priority classifier was also evaluated only against the deployed implementation and should not be interpreted as a broadly validated predictive model.

## 8. Chapter 5 Conclusion Revision

The implemented RealEstate360+ maintenance analytics were successfully integrated into the deployed system and were evaluated using owner-reviewed maintenance records. The rule-based maintenance-category detector showed acceptable preliminary alignment with the owner?s labels at 83.25% accuracy, especially for clearly expressed electrical, plumbing, and structural concerns. In contrast, the deployed maintenance-priority classifier produced weak results at 32.49% accuracy, showing that its present output should remain advisory and subject to human review. Overall, the system demonstrates functional integration of analytics into the property-management workflow, but the evaluation confirms that these components should be presented as decision-support tools rather than autonomous decision makers.

## 9. Chapter 6 Recommendation Revision

Future work should expand maintenance labeling beyond a single reviewer so that inter-rater agreement and more stable reference labels can be measured. The rule-based category detector should be improved by extending its vocabulary, reducing false keyword matches for `OTHER` cases, and adding stronger handling for spelling variations, Tagalog or Taglish expressions, and multi-issue requests. The maintenance-priority classifier should be retrained using a larger and more consistently labeled dataset, then re-evaluated before stronger claims are made about operational accuracy. Until then, the system should continue to use both maintenance analytics components only as support for Admin review and not as final automated decisions.

## 10. Appendix Description for the Owner-Reviewed Workbook

Appendix X presents the completed maintenance evaluation workbook used for the preliminary analytics assessment. The workbook contains 197 maintenance-request records and the corresponding owner-assigned reference labels for issue category and priority level. The company owner served as the single reviewer because of familiarity with the company?s maintenance operations. The workbook was completed before the generated system predictions were compared with the human labels. The appendix should note that only one reviewer participated, inter-rater agreement was not measured, and the workbook was used only to evaluate the deployed RealEstate360+ maintenance-category detector and maintenance-priority classifier on the included records.
