# RealEstate360+ Maintenance Category Owner Review

This workbook is for the company owner to provide manual reference labels for a sampled set of maintenance requests. The labels will be used only after the completed workbook is returned, as part of the preliminary evaluation of the rule-based maintenance category detector.

Only complete the `Human Label` column in the `Owner Review` sheet. The permitted labels are `PLUMBING`, `ELECTRICAL`, `STRUCTURAL`, and `OTHER`.

Do not change the `Test ID`, `Maintenance Title`, or `Maintenance Description` values. `Reviewer Notes` is optional and may be used for comments or clarification, but it is not required for the evaluation.

After labeling is complete, save the workbook as an `.xlsx` file and return that completed workbook to the research team. The import script will validate the returned file against the preserved source copy before generating the final evaluation CSV.

System predictions, matched keywords, confidence scores, and correctness results were intentionally excluded so the review remains independent of the deployed detector.

The category-evaluation process will be run only after the completed workbook has been returned and validated.
