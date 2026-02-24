import os
import requests
import pandas as pd
import json

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
RAW_SCF_FILE = os.path.join(DATA_DIR, 'scf_raw.xlsx')
PARSED_JSON_FILE = os.path.join(DATA_DIR, 'scf_parsed.json')

# We use the official GitHub API to dynamically get the latest release
GITHUB_API_URL = "https://api.github.com/repos/securecontrolsframework/securecontrolsframework/releases/latest"

def setup_directories():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def download_scf():
    """Dynamically fetches the latest SCF Excel file from GitHub releases."""
    if os.path.exists(RAW_SCF_FILE):
        print(f"[*] Found existing SCF file at {RAW_SCF_FILE}")
        return True
    
    print("[*] Fetching latest SCF release info from GitHub...")
    try:
        headers = {'Accept': 'application/vnd.github.v3+json'}
        response = requests.get(GITHUB_API_URL, headers=headers)
        response.raise_for_status()
        
        release_data = response.json()
        download_url = None
        
        for asset in release_data.get('assets', []):
            if asset['name'].endswith('.xlsx'):
                download_url = asset['browser_download_url']
                print(f"[+] Found latest release file: {asset['name']}")
                break
                
        if not download_url:
            print("[-] Could not find an .xlsx file in the latest GitHub release.")
            return False
            
        print(f"[*] Downloading from {download_url}...")
        file_response = requests.get(download_url, stream=True)
        file_response.raise_for_status()
        
        with open(RAW_SCF_FILE, 'wb') as f:
            for chunk in file_response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        print("[+] Successfully downloaded latest SCF Excel file.")
        return True
    except requests.exceptions.HTTPError as e:
        print(f"[-] HTTP Error fetching SCF: {e}")
        return False
    except Exception as e:
        print(f"[-] Error downloading SCF: {e}")
        return False

def parse_scf():
    """Parses the massive Excel file into a lightweight JSON database for the AI."""
    print("[*] Parsing SCF Excel file...")
    try:
        xls = pd.ExcelFile(RAW_SCF_FILE)
        # Find the correct main sheet, usually named "SCF 2025.4" or similar
        target_sheet = None
        for sheet in xls.sheet_names:
            if sheet.startswith('SCF ') and 'Domains & Principles' not in sheet:
                target_sheet = sheet
                break
                
        if not target_sheet:
            print("[-] Could not find the main SCF sheet. Available sheets:")
            print(xls.sheet_names)
            return False

        print(f"[*] Found main sheet: {target_sheet}")
        df = pd.read_excel(RAW_SCF_FILE, sheet_name=target_sheet) # headers usually start on row 0 now

        # We only want to keep essential columns for the AI context to save tokens
        id_col = next((col for col in df.columns if 'scf #' in str(col).lower()), None)
        domain_col = next((col for col in df.columns if 'domain' in str(col).lower() and 'scf' in str(col).lower()), None)
        desc_col = next((col for col in df.columns if 'description' in str(col).lower() and 'control' in str(col).lower()), None)
        
        if not id_col or not desc_col:
            print("[-] Could not find required columns in the Excel file.")
            print(f"Available columns: {df.columns.tolist()[:10]}")
            return False

        print(f"[+] Found columns: ID='{id_col}', Domain='{domain_col}', Description='{desc_col}'")
        
        # Identify key regulatory columns (ISO, NIST, SOC 2, GDPR, CCPA, HIPAA, PCI)
        # We search the column names for these keywords to dynamically find them
        framework_keywords = ['soc 2', 'iso 27001', 'nist csf', 'nist 800-53', 'gdpr', 'ccpa', 'hipaa', 'pci dss']
        reg_cols = []
        for col in df.columns:
            col_lower = str(col).lower().replace('\n', ' ')
            if any(kw in col_lower for kw in framework_keywords):
                reg_cols.append(col)
                
        print(f"[*] Extracting mappings for {len(reg_cols)} key frameworks/regulations...")

        # Filter and clean
        cols_to_keep = [id_col, domain_col, desc_col] + reg_cols
        cleaned_df = df[cols_to_keep].copy()
        cleaned_df = cleaned_df.dropna(subset=[id_col, desc_col])
        
        # Convert to dictionary format
        records = []
        for _, row in cleaned_df.iterrows():
            record = {
                "control_id": row[id_col],
                "domain": row[domain_col],
                "description": row[desc_col],
                "regulations": {}
            }
            # Add regulations if they are not NaN
            for r_col in reg_cols:
                val = row[r_col]
                if pd.notna(val) and str(val).strip() != "":
                    # Clean up the column name for the JSON key (remove newlines)
                    clean_name = str(r_col).replace('\n', ' ').strip()
                    record["regulations"][clean_name] = str(val).strip()
            
            records.append(record)
        
        with open(PARSED_JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
            
        print(f"[+] Successfully parsed {len(records)} controls.")
        print(f"[+] Saved lightweight AI database to {PARSED_JSON_FILE}")
        return True
        
    except Exception as e:
        print(f"[-] Error parsing Excel file: {e}")
        return False

def main():
    setup_directories()
    if download_scf():
        parse_scf()

if __name__ == "__main__":
    main()
