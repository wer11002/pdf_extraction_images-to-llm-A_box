import re
import os
import glob

def format_value(val):
    """
    Ensures 4 decimal places and leading zero.
    """
    try:
        val_float = float(val)
        # Format to 4 decimal places
        formatted = "{:.4f}".format(val_float)
        # Ensure leading zero if needed
        if formatted.startswith('.'):
            formatted = "0" + formatted
        return formatted
    except ValueError:
        return str(val)

def generate_markdown_table(rows, is_tuned=False):
    """
    Generates the standardized markdown table.
    """
    markdown = []
    
    # Context row
    context = "**Context: Tuned / Optimized Performance**" if is_tuned else "**Context: Base Performance**"
    markdown.append(context)
    markdown.append("") 
    
    # Headers
    headers = ["Model", "F1 Score", "Precision", "Recall"]
    alignments = [":---", "---:", "---:", "---:"]
    
    markdown.append("| " + " | ".join(headers) + " |")
    markdown.append("| " + " | ".join(alignments) + " |")
    
    # Data rows
    for row in rows:
        model = row['Model']
        f1 = format_value(row['F1'])
        precision = format_value(row['Precision'])
        recall = format_value(row['Recall'])
        
        markdown.append(f"| {model} | {f1} | {precision} | {recall} |")
        
    return "\n".join(markdown)

def parse_extracted_file(filepath):
    print(f"Parsing tables from {filepath}...")
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return []
    
    # Split by detected tables
    parts = content.split("=== DETECTED IMAGE-BASED TABLES ===")
    if len(parts) < 2:
        print("  No image-based tables section found.")
        return []
    
    parsed_tables = []
    
    # Iterate over all sections containing tables (skip the first part which is pre-table text)
    for table_section in parts[1:]:
        # Split by Caption within this section
        raw_tables = re.split(r"(Caption: TABLE \d+\.?)", table_section, flags=re.IGNORECASE)
        
        current_caption = ""
        
        for chunk in raw_tables:
            if chunk.startswith("Caption:"):
                current_caption = chunk.strip()
            elif current_caption:
                # Process table block
                print(f"  Processing {current_caption}...")
                tables_data = parse_table_block(chunk)
                
                for table_type, rows in tables_data.items():
                    if rows:
                        is_tuned = (table_type == "tuned")
                        md = generate_markdown_table(rows, is_tuned)
                        parsed_tables.append({
                            "caption": current_caption,
                            "markdown": md
                        })
                
                current_caption = ""
            
    return parsed_tables

def parse_table_block(text):
    lines = text.strip().split('\n')
    
    base_rows = []
    tuned_rows = []
    
    current_list = base_rows # Default to base
    
    # Regex for data row: Model Name followed by 3 floats
    # We allow some flexibility in whitespace
    # Model name can be multi-word, but usually ends before the first float
    # We look for the pattern: (Text) (Float) (Float) (Float)
    # Note: OCR might produce "0.8856" or ".8856"
    
    row_pattern = re.compile(r"^\s*(.+?)\s+([0-9]*\.\d+)\s+([0-9]*\.\d+)\s+([0-9]*\.\d+)")
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        # Try to match data row first
        match = row_pattern.search(line)
        if match:
            model_name = match.group(1).strip()
            v1 = float(match.group(2)) # Precision
            v2 = float(match.group(3)) # Recall
            v3 = float(match.group(4)) # F1
            
            # Add to current list
            current_list.append({
                "Model": model_name,
                "Precision": v1,
                "Recall": v2,
                "F1": v3
            })
            continue

        # Context detection
        lower_line = line.lower()
        if "optimal" in lower_line or "tuned" in lower_line:
            current_list = tuned_rows
            continue
        if "base" in lower_line:
            current_list = base_rows
            continue
            
    return {"base": base_rows, "tuned": tuned_rows}

def process_all_extracted_files():
    print("\n--- Starting Table Parsing & Standardization ---")
    files = glob.glob("extracted_*_enhanced.pdf.txt")
    
    if not files:
        print("No extracted text files found.")
        return
        
    summary_report = []
    
    for filepath in files:
        filename = os.path.basename(filepath)
        summary_report.append(f"# Extracted Tables from {filename}")
        
        tables = parse_extracted_file(filepath)
        
        # Append to the text file (Integration)
        try:
            with open(filepath, 'a') as f:
                f.write("\n\n=== STANDARDIZED MARKDOWN TABLES ===\n")
                if tables:
                    for t in tables:
                        f.write(f"\n## {t['caption']}\n")
                        f.write(t['markdown'])
                        f.write("\n")
                else:
                    f.write("\nNo standardized tables available.\n")
            print(f"  Integrated standardized tables into {filename}")
        except Exception as e:
            print(f"  Failed to append tables to {filename}: {e}")
        
        if tables:
            for t in tables:
                summary_report.append(f"## {t['caption']}")
                summary_report.append(t['markdown'])
                summary_report.append("")
        else:
            summary_report.append("No structured tables found or parsed.\n")
            
    # Print Report
    print("\n" + "="*50)
    print("FINAL EXECUTION RESULTS: STANDARDIZED TABLES")
    print("="*50)
    print("\n".join(summary_report))
    print("="*50 + "\n")
    
    return True

if __name__ == "__main__":
    process_all_extracted_files()
