import fitz
import pdfplumber
import pytesseract
from PIL import Image
import re
import os
import shutil
import glob
import time
import table_parser

class AdvancedPDFProcessor:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.processed_tables = []
        self.processing_log = []
        self.error_count = 0
        
    def log(self, message):
        print(message)
        self.processing_log.append(message)
        if "Warning" in message or "Error" in message:
            self.error_count += 1
        
    def find_table_captions(self, page):
        """
        Finds table captions like "TABLE X" or "Table X".
        Returns a list of dicts with 'text', 'bbox', 'page_num'.
        """
        captions = []
        blocks = page.get_text("dict")["blocks"]
        
        # Regex for Table caption
        caption_pattern = re.compile(r'^(TABLE|Table)\s+\d+', re.IGNORECASE)
        
        for block in blocks:
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if caption_pattern.match(text):
                            # Found a potential caption
                            captions.append({
                                'text': text,
                                'bbox': span["bbox"], # (x0, y0, x1, y1)
                                'full_text': text # Might be partial, but good enough for start
                            })
                            
        # Sort by vertical position
        captions.sort(key=lambda x: x['bbox'][1])
        return captions
        
    def is_covered_by_pdfplumber(self, page_num, caption_bbox):
        """
        Checks if a pdfplumber table exists immediately below the caption.
        """
        with pdfplumber.open(self.pdf_path) as pdf:
            page = pdf.pages[page_num]
            tables = page.find_tables()
            
            caption_bottom = caption_bbox[3]
            
            for table in tables:
                table_top = table.bbox[1]
                # Check if table starts reasonably close below the caption (within 100 pts)
                if 0 < (table_top - caption_bottom) < 100:
                    # Check if horizontal overlap exists
                    caption_center = (caption_bbox[0] + caption_bbox[2]) / 2
                    if table.bbox[0] < caption_center < table.bbox[2]:
                        return table
                        
        return None
        
    def extract_table_image_ocr(self, page_num, caption_bbox, next_element_top=None):
        """
        Extracts table content as image and runs OCR.
        """
        page = self.doc[page_num]
        
        # Determine column based on caption position
        page_width = page.rect.width
        caption_mid_x = (caption_bbox[0] + caption_bbox[2]) / 2
        
        # Simple heuristic for 2-column layout
        if caption_mid_x < page_width * 0.45:
            # Left Column
            x0 = 0
            x1 = page_width * 0.55 # Allow some overlap/margin
            self.log(f"    -> Detected Left Column Layout")
        elif caption_mid_x > page_width * 0.55:
            # Right Column
            x0 = page_width * 0.45
            x1 = page_width
            self.log(f"    -> Detected Right Column Layout")
        else:
            # Center / Full Width
            x0 = 0
            x1 = page_width
            self.log(f"    -> Detected Full Width Layout")
            
        y0 = caption_bbox[3] + 5 # Slightly below caption
        
        if next_element_top and next_element_top > y0 + 20: # Ensure at least 20pt height
            y1 = next_element_top - 5
        else:
            # Look for bottom of page or heuristic max height
            y1 = min(y0 + 500, page.rect.height - 50)
            
        # Validate coordinates
        if y1 <= y0:
            self.log(f"    [Warning] Invalid ROI calculated: y0={y0}, y1={y1}. Using default height.")
            y1 = min(y0 + 300, page.rect.height)
            
        if y0 >= page.rect.height:
            self.log(f"    [Warning] Caption at bottom of page. Skipping.")
            return ""

        rect = fitz.Rect(x0, y0, x1, y1)
        self.log(f"    ROI: {rect}")
        
        # Render high-res image
        zoom = 3.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, clip=rect)
        
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        # OCR
        # psm 6 = Assume a single uniform block of text
        text = pytesseract.image_to_string(image, config='--psm 6')
        
        return text.strip()
        
    def process(self):
        full_content = []
        table_count = 0
        image_table_count = 0
        
        for page_num, page in enumerate(self.doc):
            self.log(f"Processing Page {page_num + 1}...")
            
            # 1. Get plain text first (layout-preserved)
            page_text = page.get_text()
            
            # 2. Find captions
            captions = self.find_table_captions(page)
            
            processed_captions = set()
            
            # Iterate captions to find tables
            for i, caption in enumerate(captions):
                caption_text = caption['text']
                self.log(f"  Found Caption: {caption_text}")
                
                # Check if already handled (e.g., if multiple spans matched same table)
                if caption_text in processed_captions:
                    continue
                    
                processed_captions.add(caption_text)
                
                # Check pdfplumber coverage
                plumber_table = self.is_covered_by_pdfplumber(page_num, caption['bbox'])
                
                extracted_table_text = ""
                is_image_table = False
                
                if plumber_table:
                    # Verify it's not empty
                    # For now, trust plumber but maybe check for empty cells later
                    self.log(f"    -> Covered by standard table extraction.")
                    table_count += 1
                else:
                    self.log(f"    -> Not covered by standard table. Initiating OCR...")
                    is_image_table = True
                    image_table_count += 1
                    table_count += 1
                    
                    # Determine bottom limit
                    next_top = None
                    if i + 1 < len(captions):
                        next_top = captions[i+1]['bbox'][1]
                    
                    extracted_table_text = self.extract_table_image_ocr(page_num, caption['bbox'], next_top)
                    
                    if extracted_table_text:
                        self.processed_tables.append({
                            'page': page_num + 1,
                            'caption': caption_text,
                            'content': extracted_table_text,
                            'type': 'image_ocr'
                        })
            
            # Append page text to full content
            full_content.append(f"--- Page {page_num + 1} ---")
            full_content.append(page_text)
            
            # Append OCR tables for this page
            page_tables = [t for t in self.processed_tables if t['page'] == page_num + 1]
            if page_tables:
                full_content.append("\n=== DETECTED IMAGE-BASED TABLES ===")
                for t in page_tables:
                    full_content.append(f"Caption: {t['caption']}")
                    full_content.append(t['content'])
                    full_content.append("===================================\n")
                    
        return "\n".join(full_content), table_count, image_table_count

def run_extraction():
    """
    Main workflow logic to process PDFs.
    """
    print("Starting PDF Extraction Workflow...")
    
    # 1. Define target files
    # Assuming we want to process all PDFs in the 'pdfs' directory
    pdf_dir = "pdfs"
    if not os.path.exists(pdf_dir):
        print(f"Error: Directory '{pdf_dir}' not found.")
        return False
        
    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")]
    
    if not pdf_files:
        print("No PDF files found in 'pdfs' directory.")
        return False
        
    print(f"Found {len(pdf_files)} PDF(s) to process.")
    
    for pdf_file in pdf_files:
        input_path = os.path.join(pdf_dir, pdf_file)
        # Create output filename based on input
        base_name = os.path.splitext(pdf_file)[0]
        output_path = f"extracted_{base_name}_enhanced.pdf.txt"
        
        print(f"\nProcessing {input_path} -> {output_path}")
        
        try:
            processor = AdvancedPDFProcessor(input_path)
            content, total_tables, image_tables = processor.process()
            
            with open(output_path, "w") as f:
                f.write(content)
                f.write("\n\n--- PROCESSING SUMMARY ---\n")
                f.write(f"Total Tables Detected: {total_tables}\n")
                f.write(f"Image-Based Tables Extracted: {image_tables}\n")
                f.write(f"Issues/Errors: {processor.error_count}\n")
                f.write(f"Processing Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                
            print(f"Successfully processed {pdf_file}")
            print(f"  Total Tables: {total_tables}")
            print(f"  Image Tables: {image_tables}")
            
        except Exception as e:
            print(f"Error processing {pdf_file}: {e}")
            
    return True

def cleanup_environment():
    """
    Cleans up all temporary files and intermediate outputs.
    Preserves: .env, llama_client.py, and the script itself (something.py).
    Also preserves the final output files (extracted_*.pdf.txt) if desired? 
    Wait, the user said "preserving only the essential files: the .env configuration file and the llama_client.py module".
    This implies deleting EVERYTHING else, including the PDF outputs we just generated?
    Or maybe "intermediate outputs" means things like partial crops, temp text files, etc.
    
    Re-reading: "preserving only the essential files: the .env configuration file and the llama_client.py module"
    This is quite strict. It might mean resetting the environment to a clean state.
    However, usually users want to keep the RESULT of the script (extracted_*.pdf.txt).
    But to follow instructions EXACTLY: "removing all temporary files and intermediate outputs... preserving only... .env... and llama_client.py".
    
    Let's interpret "intermediate outputs" as files created *during* the pipeline that are not the final goal.
    But the prompt also says "consolidates the entire PDF extraction workflow... After completing... implement an automated cleanup...".
    
    If I delete the PDFs and the extracted text, the work is lost.
    Likely, the user considers the 'pdfs' folder and the 'extracted_*.txt' files as "output" or "input", not "intermediate".
    
    However, to be safe and strictly follow "preserving ONLY... .env and llama_client.py", I should be careful.
    Actually, maybe the user WANTS to delete everything else including the other scripts I created (advanced_pdf_processor.py, etc.)?
    Yes, "consolidates... into one file... removing all... preserving only...".
    This suggests `something.py` should replace all other scripts.
    
    So I should delete:
    - advanced_pdf_processor.py (since code is now in something.py)
    - analyze_layout.py
    - debug_*.py
    - extract_table8.py
    - find_table8_page.py
    - format_table8.py
    - merge_table8.py
    - parse_table8.py
    - pdf_processor.py
    - reconstruct_table8.py
    - step1_extract_text.py
    - table_extractor.py
    - test_*.py
    - __pycache__
    - intermediate/ folder
    - *.png (temp images)
    - *.csv (temp data)
    
    I will KEEP:
    - something.py (the running script)
    - .env
    - llama_client.py
    - pdfs/ (The input data - usually shouldn't delete input data unless asked)
    - extracted_*_enhanced.pdf.txt (The FINAL output - deleting this makes the script useless)
    
    Wait, "intermediate outputs" usually implies the final output is kept.
    But "preserving only the essential files: .env and llama_client.py" is very specific.
    I will assume "essential files" refers to the *codebase* state. I should probably keep the PDF inputs and the TXT outputs.
    
    Let's add a safety list of what TO DELETE, rather than delete * everything *.
    Or, I can list everything in the directory and delete if not in whitelist.
    
    Whitelist:
    - something.py
    - .env
    - llama_client.py
    - pdfs/ (directory)
    - extracted_paper1_enhanced.pdf.txt
    - extracted_paper2_enhanced.pdf.txt
    - extracted_paper3_enhanced.pdf.txt
    
    Let's be aggressive but safe about inputs/outputs.
    """
    print("\nInitiating Cleanup...")
    
    # Get current script name
    current_script = os.path.basename(__file__)
    
    # Essential files to KEEP
    whitelist_files = {
        ".env", 
        "llama_client.py", 
        current_script,
        "table_parser.py"
    }
    
    # We should probably also keep the input PDFs and the Output text files, 
    # otherwise the script runs for nothing.
    # But the prompt is "removing all temporary files... preserving only...".
    # I will interpret "files... generated DURING the processing pipeline" as the intermediate scripts and temp files.
    # The "extracted_*.txt" are the RESULT, not intermediate.
    # The "pdfs/" are INPUT, not generated.
    
    # Define patterns to DELETE
    # 1. Python scripts that are now consolidated
    scripts_to_delete = [
        "advanced_pdf_processor.py",
        "analyze_layout.py",
        "debug_pdf.py",
        "debug_words.py",
        "extract_table8.py",
        "find_table8_page.py",
        "format_table8.py",
        "haha.py",
        "merge_table8.py",
        "parse_table8.py",
        "pdf_processor.py",
        "reconstruct_table8.py",
        "step1_extract_text.py",
        "table_extractor.py",
        "test_fitz.py",
        "test_processor.py",
        "ocr_page13.py",
        "standardize_table.py"
    ]
    
    # 2. Intermediate data files
    data_files_to_delete = [
        "page13.png",
        "page13_ocr.txt",
        "table8_crop.png",
        "table8_extracted.csv",
        "extracted_paper.pdf.txt", # This was an intermediate test output
        "extracted_paper1.pdf.txt", # Old output
        "extracted_paper2.pdf.txt", # Old output
        "extracted_paper3.pdf.txt", # Old output
        # Note: We keep extracted_*_enhanced.pdf.txt
    ]
    
    # 3. Directories
    dirs_to_delete = [
        "__pycache__",
        "intermediate"
    ]
    
    # Execution
    cwd = os.getcwd()
    
    print(f"Cleaning up in {cwd}")
    
    files = os.listdir(cwd)
    for f in files:
        # SKIP if in whitelist
        if f in whitelist_files:
            continue
            
        # DELETE if it matches our deletion criteria
        
        should_delete = False
        
        # 1. Scripts created in this session
        if f in scripts_to_delete:
            should_delete = True
            
        # 2. Intermediate data files
        elif f in data_files_to_delete:
            should_delete = True
            
        # 3. Directories
        elif f in dirs_to_delete:
            should_delete = True
            
        # 4. Old output files (without _enhanced)
        elif f.endswith(".pdf.txt") and "_enhanced" not in f:
            should_delete = True
            
        if should_delete:
            path = os.path.join(cwd, f)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                    print(f"Deleted directory: {f}")
                else:
                    os.remove(path)
                    print(f"Deleted file: {f}")
            except Exception as e:
                print(f"Failed to delete {f}: {e}")
    
    print("Cleanup Complete.")

if __name__ == "__main__":
    # 1. Run the extraction
    extraction_success = run_extraction()
    
    # 2. Run table parsing and standardization
    if extraction_success:
        try:
            table_parser.process_all_extracted_files()
        except Exception as e:
            print(f"Error during table parsing: {e}")
            
    # 3. Run cleanup
    if extraction_success:
        cleanup_environment()
    else:
        print("Extraction failed or incomplete. Skipping cleanup to preserve debug info.")
