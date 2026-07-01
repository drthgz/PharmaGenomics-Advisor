# Biomedical Foundations

> This document explains the biology and clinical concepts behind the PharmaGenomics Advisor. No prior biology background is assumed beyond high school level.

## Table of Contents

1. [DNA, Genes, and Variants](#dna-genes-and-variants)
2. [Cancer Genomics](#cancer-genomics)
3. [Variant Classification (ACMG/AMP)](#variant-classification-acmgamp)
4. [Pharmacogenomics](#pharmacogenomics)
5. [Key Genes in This Project](#key-genes-in-this-project)
6. [Clinical Workflow (Before AI)](#clinical-workflow-before-ai)
7. [Glossary](#glossary)

---

## DNA, Genes, and Variants

### What is DNA?

DNA (deoxyribonucleic acid) is a long molecule that stores the instructions your body uses to build and maintain itself. Think of it as a recipe book. It's made of four chemical "letters" — A, T, C, and G — arranged in a specific sequence.

### What is a Gene?

A gene is a section of DNA that contains the instructions for making one specific protein. Humans have roughly 20,000 genes. Each gene has a specific location (called a "locus") on a chromosome.

### What is a Variant?

A variant (sometimes called a mutation) is a change in the DNA sequence compared to the "reference" sequence that most people carry. For example:

- **Reference:** ...ATCGATCG...
- **Variant:**   ...ATC**A**ATCG... (the G changed to an A)

Most variants are harmless. Some are beneficial. A small number cause disease or change how drugs work in your body.

### Types of Variants

| Type | What Happens | Example |
|------|-------------|---------|
| **Missense** | One amino acid changes to another | BRCA1 c.185A>G |
| **Nonsense** | Creates a premature stop signal | TP53 R213* |
| **Frameshift** | Shifts the reading frame, garbling the protein | BRCA2 6174delT |
| **Silent** | Changes DNA letter but protein stays the same | Usually harmless |

---

## Cancer Genomics

### How Variants Cause Cancer

Cancer happens when cells grow uncontrollably. Certain genes act as "brakes" (tumor suppressors like TP53) or "gas pedals" (oncogenes like EGFR). When variants break these controls:

- **Tumor suppressors** (TP53, BRCA1/2): Normally prevent cancer. A damaging variant removes the brakes.
- **Oncogenes** (EGFR): Normally promote controlled growth. A variant jams the gas pedal "on."

### Why Genomic Testing Matters

When a patient is diagnosed with cancer, doctors can sequence the tumor's DNA to find which variants are driving the cancer. This tells them:

1. **Prognosis** — How aggressive is this cancer likely to be?
2. **Treatment selection** — Which drugs target this specific variant?
3. **Hereditary risk** — Does the patient's family need testing too?

### The VCF File

After DNA sequencing, the raw data is processed through a bioinformatics pipeline that produces a **VCF file** (Variant Call Format). This is a standardized text file listing every variant found. Each line contains:

```
CHROM  POS      ID   REF  ALT  QUAL  FILTER  INFO
chr17  41234470  .   A    G    99    PASS    Gene=BRCA1;Type=missense
```

- **CHROM**: Chromosome number (chr1-chr22, chrX, chrY)
- **POS**: Position on that chromosome
- **REF**: The reference (expected) base
- **ALT**: The alternate (variant) base found in the patient
- **QUAL**: Confidence score that this variant is real
- **INFO**: Additional annotations (gene name, variant type, etc.)

---

## Variant Classification (ACMG/AMP)

### The 5-Tier System

Not every variant is dangerous. The American College of Medical Genetics (ACMG) and the Association for Molecular Pathology (AMP) created a standardized 5-tier system to classify variants:

| Classification | Meaning | Clinical Action |
|---------------|---------|----------------|
| **Pathogenic** | Causes disease | Act on it — change treatment |
| **Likely Pathogenic** | Probably causes disease (>90% certainty) | Usually act on it |
| **VUS** (Variant of Uncertain Significance) | Not enough evidence | Don't act — gather more data |
| **Likely Benign** | Probably harmless (>90% certainty) | Generally ignore |
| **Benign** | Definitely harmless | Ignore |

### How Classification Works

Classifying a variant involves weighing multiple types of evidence:

1. **Population frequency** — Is this variant common in healthy people? (Common = probably benign)
2. **Functional studies** — Has anyone tested this variant in a lab?
3. **Computational prediction** — Do algorithms predict it damages the protein?
4. **Clinical data** — Has this variant been seen in patients with the disease?
5. **Database entries** — What does ClinVar (a public database) say about it?

Each piece of evidence is assigned a strength level (Strong, Moderate, Supporting), and the final classification is determined by combining them according to published rules.

---

## Pharmacogenomics

### What is Pharmacogenomics (PGx)?

Pharmacogenomics is the study of how your genes affect your response to drugs. Different people can respond very differently to the same medication because of their genetic variants.

**Real-world example:** The drug clopidogrel (Plavix) prevents blood clots. It requires the CYP2C19 enzyme to activate it. People with certain CYP2C19 variants ("poor metabolizers") can't activate the drug — it simply doesn't work for them, putting them at risk for heart attacks.

### Why It Matters

- ~95% of people carry at least one actionable pharmacogenomic variant
- Adverse drug reactions cause ~100,000 deaths/year in the US
- Many of these are preventable with genetic testing

### CPIC Guidelines

The Clinical Pharmacogenetics Implementation Consortium (CPIC) publishes free, evidence-based guidelines that translate genetic test results into prescribing recommendations. For example:

> **Gene:** CYP2C19  
> **Drug:** Clopidogrel  
> **Phenotype:** Poor Metabolizer  
> **Recommendation:** Use alternative antiplatelet therapy (e.g., prasugrel, ticagrelor)  
> **Evidence Level:** A (strong)

CPIC currently covers 34 genes and 164 drugs.

### PharmGKB

PharmGKB (Pharmacogenomics Knowledge Base) is a comprehensive database that catalogs:
- Drug-gene associations with evidence levels
- Clinical annotations from published studies
- Dosing guidelines from multiple organizations
- Variant-specific drug response data

### How PGx Connects to Cancer Genomics

In our pipeline, after classifying a cancer variant, we check:

1. **Does this variant affect drug metabolism?** → CPIC guidelines
2. **Are there targeted therapies for this variant?** → PharmGKB annotations
3. **What drugs should be avoided or dose-adjusted?** → Treatment recommendations

Example flow:
```
EGFR L858R variant found
  → Classified as Pathogenic
  → EGFR_Agent notes: "TKI-sensitive"
  → PGx_Drug_Advisor checks PharmGKB
  → Recommendation: "Osimertinib (Tagrisso) — first-line targeted therapy"
```

---

## Key Genes in This Project

### BRCA1 / BRCA2 (Hereditary Cancer)

- **Normal function:** DNA repair (fixes double-strand breaks)
- **When broken:** Cannot repair DNA properly → cancer risk increases dramatically
- **Associated cancers:** Breast (up to 70% lifetime risk), ovarian, prostate, pancreatic
- **Key drug interaction:** PARP inhibitors (olaparib, rucaparib) specifically target BRCA-deficient tumors
- **Inheritance:** Autosomal dominant — 50% chance of passing to children

### EGFR (Lung Cancer)

- **Normal function:** Signals cells to grow and divide
- **When mutated:** Sends constant "grow" signals even without external triggers
- **Associated cancers:** Non-small cell lung cancer (NSCLC), especially in non-smokers
- **Key drug interaction:** Tyrosine kinase inhibitors (TKIs) like osimertinib block the overactive EGFR
- **Key mutations:**
  - L858R (exon 21) — TKI-sensitive
  - T790M (exon 20) — resistance to first-gen TKIs
  - Exon 19 deletions — TKI-sensitive

### TP53 (Tumor Suppressor)

- **Normal function:** "Guardian of the genome" — triggers cell death when DNA is too damaged to repair
- **When broken:** Damaged cells survive and accumulate more mutations → cancer
- **Associated cancers:** Found in ~50% of all human cancers
- **Key distinction:**
  - **Loss-of-function:** Protein stops working (most common)
  - **Gain-of-function:** Protein actively promotes cancer growth (worse prognosis)
- **Drug relevance:** Affects chemotherapy sensitivity; gain-of-function variants may respond to targeted agents in clinical trials

---

## Clinical Workflow (Before AI)

Understanding what happens today without our system helps explain what we're automating:

```
Day 1-7: Tumor biopsy → DNA extracted → Sequenced (Next-Gen Sequencing)
         ↓
Day 7-14: Bioinformatician runs variant calling pipeline → Produces VCF file
         ↓
Day 14-24: Molecular pathologist manually:
           1. Looks up each variant in ClinVar
           2. Reviews published literature
           3. Applies ACMG classification rules
           4. Checks CPIC/PharmGKB for drug implications
           5. Writes clinical report
         ↓
Day 24-28: Report reviewed, signed, sent to oncologist
         ↓
Day 28+: Oncologist discusses results with patient, adjusts treatment
```

**Total time: 2-4 weeks.** During this time, the cancer is growing.

**Our system automates steps 3-5**, reducing the interpretation phase from 7-10 days to minutes. The molecular pathologist still reviews the AI-generated report (human-in-the-loop), but instead of starting from scratch, they're validating pre-computed results.

---

## Glossary

| Term | Definition |
|------|-----------|
| **Allele** | One version of a gene at a specific position |
| **Amino acid** | Building block of proteins (20 types) |
| **Annotation** | Adding functional information to a raw variant |
| **Autosomal dominant** | Only one copy of variant needed to cause effect |
| **Bioinformatics** | Using computers to analyze biological data |
| **Chromosome** | Packaged structure of DNA (humans have 23 pairs) |
| **ClinVar** | NIH public database of variant-disease relationships |
| **CPIC** | Clinical Pharmacogenetics Implementation Consortium |
| **Exon** | Coding region of a gene (makes protein) |
| **Frameshift** | Insertion/deletion that shifts the reading frame |
| **Genotype** | The specific alleles a person carries |
| **Germline** | Inherited variant (present in every cell) |
| **HGVS** | Standard nomenclature for describing variants (e.g., c.185A>G) |
| **Missense** | Variant that changes one amino acid to another |
| **NGS** | Next-Generation Sequencing — high-throughput DNA reading |
| **Nonsense** | Variant that creates a premature stop codon |
| **Oncogene** | Gene that promotes cell growth (cancer driver when mutated) |
| **PARP inhibitor** | Drug that kills BRCA-deficient cancer cells |
| **Pathogenic** | Disease-causing |
| **Phenotype** | Observable characteristics resulting from genotype |
| **PharmGKB** | Pharmacogenomics Knowledge Base |
| **Somatic** | Variant acquired in tumor cells only (not inherited) |
| **TKI** | Tyrosine Kinase Inhibitor — blocks growth signals |
| **Tumor suppressor** | Gene that prevents cancer (brake pedal) |
| **VCF** | Variant Call Format — standard file for listing variants |
| **VUS** | Variant of Uncertain Significance |
