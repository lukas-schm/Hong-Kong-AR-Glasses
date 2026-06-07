"""CDARS — Clinical Data Analysis and Reporting System (realistic mock).

A faithful, synthetic re-creation of the Hospital Authority's central
analytics warehouse:

  · relational, encounter-based EHR warehouse (SQLite back end)
  · territory-wide coverage: all HA clusters/hospitals since 1995
  · ICD-9-CM diagnoses, BNF-classified dispensing, HA local lab codes,
    microbiology, procedures, HK Death Registry linkage
  · de-identified Reference Keys for research extracts; the identity
    vault (HKID ↔ key) exists only inside HA for current admissions
  · audit log on every query and write (Data Sharing Portal style)
"""
