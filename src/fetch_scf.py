import json
import logging
import re
import os

import pandas as pd
import requests
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
RAW_SCF_FILE = os.path.join(DATA_DIR, "scf_raw.xlsx")
PARSED_JSON_FILE = os.path.join(DATA_DIR, "scf_parsed.json")


class SCFControl(BaseModel):
    """Pydantic schema for a parsed SCF control record. Validates structure post-parse."""

    control_id: str = Field(
        ..., description="SCF control ID, e.g. 'GOV-01' or 'CLD-02.1'"
    )
    domain: str = Field(default="", description="SCF Domain name")
    description: str = Field(..., description="Control description text")
    weight: int = Field(
        default=1, ge=1, le=10, description="Relative control weighting 1-10"
    )
    erl: str = Field(default="", description="Evidence Request List")
    question: str = Field(default="", description="SCF control question")
    regulations: dict = Field(
        default_factory=dict, description="Regulatory framework mappings"
    )

    @field_validator("control_id")
    @classmethod
    def validate_control_id_format(cls, v: str) -> str:
        if not re.match(r"^[A-Z]{2,6}-\d{2}(\.\d+)?$", v):
            raise ValueError(f"Invalid SCF control ID format: '{v}'")
        return v


# We use the official GitHub API to dynamically get the latest release
GITHUB_API_URL = "https://api.github.com/repos/securecontrolsframework/securecontrolsframework/releases/latest"


def setup_directories():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def download_scf():
    """Dynamically fetches the latest SCF Excel file from GitHub releases."""
    if os.path.exists(RAW_SCF_FILE):
        logger.info("Found existing SCF file at %s", RAW_SCF_FILE)
        return True

    logger.info("Fetching latest SCF release info from GitHub...")
    try:
        headers = {"Accept": "application/vnd.github.v3+json"}
        response = requests.get(GITHUB_API_URL, headers=headers, timeout=10)
        response.raise_for_status()

        release_data = response.json()
        download_url = None

        for asset in release_data.get("assets", []):
            if asset["name"].endswith(".xlsx"):
                download_url = asset["browser_download_url"]
                logger.info("Found latest release file: %s", asset["name"])
                break

        if not download_url:
            logger.error("Could not find an .xlsx file in the latest GitHub release.")
            return False

        logger.info("Downloading from %s...", download_url)
        file_response = requests.get(download_url, stream=True, timeout=10)
        file_response.raise_for_status()

        with open(RAW_SCF_FILE, "wb") as f:
            for chunk in file_response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info("Successfully downloaded latest SCF Excel file.")
        return True
    except requests.exceptions.HTTPError as e:
        logger.error("HTTP Error fetching SCF: %s", e)
        return False
    except Exception as e:
        logger.error("Error downloading SCF: %s", e)
        return False


def parse_scf():
    """Parses the massive Excel file into a lightweight JSON database for the AI."""
    logger.info("Parsing SCF Excel file...")
    try:
        xls = pd.ExcelFile(RAW_SCF_FILE)
        # Find the correct main sheet, usually named "SCF 2025.4" or similar
        target_sheet = None
        for sheet in xls.sheet_names:
            if sheet.startswith("SCF ") and "Domains & Principles" not in sheet:
                target_sheet = sheet
                break

        if not target_sheet:
            logger.error(
                "Could not find the main SCF sheet. Available sheets: %s",
                xls.sheet_names,
            )
            return False

        logger.info("Found main sheet: %s", target_sheet)
        df = pd.read_excel(
            RAW_SCF_FILE, sheet_name=target_sheet
        )  # headers usually start on row 0 now

        # We only want to keep essential columns for the AI context to save tokens
        id_col = next((col for col in df.columns if "scf #" in str(col).lower()), None)
        domain_col = next(
            (
                col
                for col in df.columns
                if "domain" in str(col).lower() and "scf" in str(col).lower()
            ),
            None,
        )
        desc_col = next(
            (
                col
                for col in df.columns
                if "description" in str(col).lower() and "control" in str(col).lower()
            ),
            None,
        )
        weight_col = next(
            (
                col
                for col in df.columns
                if "relative control weighting" in str(col).lower()
            ),
            None,
        )
        erl_col = next(
            (col for col in df.columns if "evidence request list" in str(col).lower()),
            None,
        )
        question_col = next(
            (col for col in df.columns if "scf control question" in str(col).lower()),
            None,
        )

        if not id_col or not desc_col:
            logger.error(
                "Could not find required columns in the Excel file. Available: %s",
                df.columns.tolist()[:10],
            )
            return False

        logger.info(
            "Found columns: ID='%s', Domain='%s', Description='%s', Weight='%s'",
            id_col,
            domain_col,
            desc_col,
            weight_col,
        )

        # Identify key regulatory columns (ISO, NIST, SOC 2, GDPR, CCPA, HIPAA, PCI)
        # We search the column names for these keywords to dynamically find them
        framework_keywords = [
            "soc 2",
            "iso 27001",
            "nist csf",
            "nist 800-53",
            "gdpr",
            "ccpa",
            "hipaa",
            "pci dss",
        ]
        reg_cols = []
        for col in df.columns:
            col_lower = str(col).lower().replace("\n", " ")
            if any(kw in col_lower for kw in framework_keywords):
                reg_cols.append(col)

        logger.info(
            "Extracting mappings for %d key frameworks/regulations...", len(reg_cols)
        )

        # Filter and clean
        cols_to_keep = [id_col, domain_col, desc_col] + reg_cols
        if weight_col:
            cols_to_keep.append(weight_col)
        if erl_col:
            cols_to_keep.append(erl_col)
        if question_col:
            cols_to_keep.append(question_col)

        cleaned_df = df[cols_to_keep].copy()
        cleaned_df = cleaned_df.dropna(subset=[id_col, desc_col])

        # Convert to dictionary format
        records = []
        for _, row in cleaned_df.iterrows():
            weight_val = (
                row[weight_col] if weight_col and pd.notna(row[weight_col]) else 1
            )
            # SCF usually has weights from 1 to 10
            try:
                weight_val = int(weight_val)
            except ValueError:
                weight_val = 1

            erl_val = row[erl_col] if erl_col and pd.notna(row[erl_col]) else ""
            question_val = (
                row[question_col]
                if question_col and pd.notna(row[question_col])
                else ""
            )

            record = {
                "control_id": row[id_col],
                "domain": row[domain_col],
                "description": row[desc_col],
                "weight": weight_val,
                "erl": str(erl_val).strip(),
                "question": str(question_val).strip(),
                "regulations": {},
            }
            # Add regulations if they are not NaN
            for r_col in reg_cols:
                val = row[r_col]
                if pd.notna(val) and str(val).strip() != "":
                    # Clean up the column name for the JSON key (remove newlines)
                    clean_name = str(r_col).replace("\n", " ").strip()
                    record["regulations"][clean_name] = str(val).strip()

            # Validate record shape with Pydantic before storing
            try:
                SCFControl(**record)
            except Exception as validation_err:
                logger.warning(
                    "Skipping control '%s' — failed schema validation: %s",
                    record.get("control_id", "UNKNOWN"),
                    validation_err,
                )
                continue

            records.append(record)

        with open(PARSED_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

        logger.info("Successfully parsed %d controls.", len(records))
        logger.info("Saved lightweight AI database to %s", PARSED_JSON_FILE)
        return True

    except Exception as e:
        logger.error("Error parsing Excel file: %s", e)
        return False


def main():
    logging.basicConfig(level=logging.INFO)
    setup_directories()
    if download_scf():
        parse_scf()


if __name__ == "__main__":
    main()
